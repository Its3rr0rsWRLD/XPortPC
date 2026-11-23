// GFX10.3 (RDNA2) hardware descriptor words: decoding the T# (image), S# (sampler) and V# (buffer) a console title
// writes into descriptor memory, and the desktop objects that match them (docs/design/runtime.md, "Descriptors
// written as hardware words").
//
// Field positions and enumerations are those of Mesa's register database for GFX10/GFX10.3
// (src/amd/registers/gfx10-rsrc.json, the *_gfx103 variants of words 4-6 of the T# and word 3 of the V#; the
// enumerations from gfx6.json), as Mesa's ac_descriptors.c (MIT) builds them: kFields lists every field this decoder
// reads, and tests/gfx10_descriptors_fields_check.py compares that table and kImageFormats' hardware numbers with the
// pinned Mesa release. The GFX10 T# stores the address shifted right by 8 with the surface's pipe/bank XOR (Mesa's
// tile_swizzle, addrlib's pipeBankXor) ORed into its low bits (ac_set_mutable_tex_desc_fields); PlanTexture takes
// it back out for the swizzle modes that use one.
//
// No D3D12 types here, so the same code builds and is tested on Linux (tests/gfx10_descriptors_check.cpp). The
// desktop side is plain numbers: DXGI_FORMAT values, D3D12_SHADER_COMPONENT_MAPPING encodings and a struct laid out
// as D3D12_SAMPLER_DESC; the graphics shim static_asserts each against the Windows SDK (src/d3d12_xs_pipeline.cpp).

#pragma once

#include "gfx10_addr.h"

#include <cstdint>
#include <string>

namespace x2w::gfx10
{

// One field of a descriptor word: Mesa's register (SQ_IMG_RSRC_WORDn, SQ_IMG_SAMP_WORDn, SQ_BUF_RSRC_WORDn, with
// Mesa's _gfx103 suffix where the GFX10.3 layout differs) and field name, and its bits.
struct Field
{
    const char* reg;
    const char* name;
    std::uint8_t word;  // dword index within the descriptor
    std::uint8_t lo, hi;
};
extern const Field kFields[];
extern const unsigned kFieldCount;
// Lookups of a field name kFields does not have since the process started (a bug; the CPU check requires 0).
unsigned FieldLookupFailures();

// SQ_SEL_XYZW01 (gfx6.json).
enum Sel : std::uint32_t { SelZero = 0, SelOne = 1, SelX = 4, SelY = 5, SelZ = 6, SelW = 7 };
// SQ_RSRC_IMG_TYPE (gfx6.json).
enum ImageType : std::uint32_t
{
    Img1D = 8, Img2D = 9, Img3D = 10, ImgCube = 11, Img1DArray = 12, Img2DArray = 13, Img2DMsaa = 14,
    Img2DMsaaArray = 15
};

// An image format the shim can create a desktop texture for. `gfx10` is the T#'s FORMAT (GFX10_FORMAT in
// gfx10-rsrc.json); `dxgi` the DXGI_FORMAT value. `channel[c]` is the DXGI component that holds hardware channel c
// (the hardware numbers channels from the lowest bits, as Mesa's gfx10_format_table.py reads the names; DXGI's
// B5G6R5-style formats keep blue in the low bits, so their red is hardware channel 2).
struct ImageFormat
{
    std::uint32_t gfx10;
    const char* name;  // GFX10_FORMAT_<name>
    std::uint32_t dxgi;
    std::uint8_t element_bytes;  // bytes per element (a 4x4 block for BC formats)
    std::uint8_t block;          // pixels per element edge: 1, or 4 for BC formats
    std::uint8_t channel[4];
};
extern const ImageFormat kImageFormats[];
extern const unsigned kImageFormatCount;
const ImageFormat* FindImageFormat(std::uint32_t gfx10_format);

// The T# fields (GFX10.3 layout).
struct ImageDescriptor
{
    std::uint64_t address_field = 0;  // BASE_ADDRESS | BASE_ADDRESS_HI << 32: address bits 39:8, pipe/bank XOR ORed in
    std::uint32_t min_lod = 0;        // u4.8
    std::uint32_t format = 0;
    std::uint32_t width = 0, height = 0;  // pixels (the fields hold size - 1)
    std::uint32_t dst_sel[4] = {};
    std::uint32_t base_level = 0, last_level = 0;
    std::uint32_t sw_mode = 0;
    std::uint32_t bc_swizzle = 0;
    std::uint32_t type = 0;
    std::uint32_t depth = 0, pitch_msb = 0, base_array = 0;
    std::uint32_t array_pitch = 0, max_mip = 0;
    std::uint32_t compression_en = 0;
};
void DecodeImage(const std::uint32_t words[8], ImageDescriptor* out);

// The S# fields.
struct SamplerDescriptor
{
    std::uint32_t clamp_x = 0, clamp_y = 0, clamp_z = 0;  // SQ_TEX_CLAMP
    std::uint32_t max_aniso_ratio = 0;                      // log2 of the ratio
    std::uint32_t depth_compare_func = 0;                   // SQ_TEX_DEPTH_COMPARE
    std::uint32_t force_unnormalized = 0, aniso_threshold = 0, mc_coord_trunc = 0, force_degamma = 0;
    std::uint32_t aniso_bias = 0, trunc_coord = 0, disable_cube_wrap = 0, filter_mode = 0, skip_degamma = 0;
    std::uint32_t min_lod = 0, max_lod = 0;  // u4.8
    std::uint32_t perf_mip = 0, perf_z = 0;
    std::uint32_t lod_bias = 0;              // s5.8, 14 bits
    std::uint32_t lod_bias_sec = 0;
    std::uint32_t xy_mag_filter = 0, xy_min_filter = 0, z_filter = 0, mip_filter = 0;
    std::uint32_t mip_point_preclamp = 0, aniso_override = 0, blend_zero_prt = 0;
    std::uint32_t border_color_ptr = 0, border_color_type = 0;
};
void DecodeSampler(const std::uint32_t words[4], SamplerDescriptor* out);

// The V# fields (GFX10.3 layout).
struct BufferDescriptor
{
    std::uint64_t address = 0;  // bytes
    std::uint32_t stride = 0;
    std::uint32_t cache_swizzle = 0, swizzle_enable = 0;
    std::uint32_t num_records = 0;
    std::uint32_t dst_sel[4] = {};
    std::uint32_t format = 0;
    std::uint32_t index_stride = 0, add_tid_enable = 0, resource_level = 0, oob_select = 0, type = 0;
};
void DecodeBuffer(const std::uint32_t words[4], BufferDescriptor* out);

// What the shim creates for a T#: a desktop 2D texture holding the title's bytes, detiled with the surface below
// (src/gfx10_detile.h), and a Texture2D SRV over it.
struct TexturePlan
{
    std::uint64_t address = 0;         // the surface's base address in title memory (pipe/bank XOR removed)
    std::uint64_t bytes = 0;           // addrlib surfSize: what the detiler reads from `address`
    Surface surface;                   // mode, element size, size, mips (MAX_MIP + 1), pipe/bank XOR
    std::uint32_t dxgi_format = 0;
    std::uint32_t most_detailed_mip = 0, mip_levels = 0;  // the SRV's range: BASE_LEVEL..LAST_LEVEL
    float min_lod_clamp = 0.0f;                           // MIN_LOD
    std::uint32_t component_mapping = 0;                  // D3D12_ENCODE_SHADER_4_COMPONENT_MAPPING of DST_SEL
};
// False, with the reason, for a T# the shim does not bind: not a 2D image, a format without a desktop equivalent
// here, DCC compression, an array slice range, a custom linear pitch, inconsistent levels, or a surface the detiler
// does not cover (ComputeLayout's reason).
bool PlanTexture(const Config& config, const ImageDescriptor& d, TexturePlan* out, std::string* why);

// D3D12_SAMPLER_DESC, field for field (the shim static_asserts the layout).
struct DesktopSampler
{
    std::uint32_t filter;     // D3D12_FILTER
    std::uint32_t address_u;  // D3D12_TEXTURE_ADDRESS_MODE
    std::uint32_t address_v;
    std::uint32_t address_w;
    float mip_lod_bias;
    std::uint32_t max_anisotropy;
    std::uint32_t comparison_func;  // D3D12_COMPARISON_FUNC
    float border_color[4];
    float min_lod;
    float max_lod;
};
// False, with the reason, for an S# without a desktop equivalent: half-border clamps, a border colour from the
// border-colour table, unnormalized coordinates, degamma overrides, a secondary LOD bias, a LOD bias outside D3D12's
// range, anisotropy with point mip filtering.
bool PlanSampler(const SamplerDescriptor& d, DesktopSampler* out, std::string* why);

// What a constant-buffer V# covers: false, with the reason, for a V# that is not a plain buffer (TYPE), swizzled or
// with ADD_TID. `bytes` is the range its out-of-bounds check allows for dword reads at byte offsets
// (num_records, or num_records * stride when the stride is not 0).
bool PlanConstantBuffer(const BufferDescriptor& d, std::uint64_t* address, std::uint64_t* bytes, std::string* why);

// u4.8 and s5.8 fixed point (Mesa's util_unsigned_fixed / util_signed_fixed with 8 fractional bits) to float.
float UnsignedFixed8(std::uint32_t value);
float SignedFixed8(std::uint32_t value, unsigned bits);

}  // namespace x2w::gfx10
