#pragma once

// Hardware descriptor words as a console title writes them into descriptor memory (R6 descriptors), for
// tests/runtime/r6_rawdesc_*.cpp. The bit positions are those of Mesa's gfx10-rsrc.json (GFX10.3 layouts), the way
// Mesa's ac_build_gfx10_texture_descriptor, ac_set_mutable_tex_desc_fields, ac_build_sampler_descriptor and
// ac_build_buffer_descriptor fill them (MIT). Written out here, field by field, rather than taken from the shim's
// decoder (src/gfx10_descriptors.h), so a decoder that read a field from the wrong bits draws a wrong frame.

#include "d3d12_xs_api.h"

#include <cstdint>
#include <cstring>
#include <vector>

namespace r6 {

constexpr std::uint32_t put(std::uint32_t value, unsigned lo, unsigned hi)
{
    return (value & (hi - lo == 31 ? ~0u : ((1u << (hi - lo + 1)) - 1))) << lo;
}

// SQ_SEL_XYZW01.
enum : std::uint32_t { sel_0 = 0, sel_1 = 1, sel_x = 4, sel_y = 5, sel_z = 6, sel_w = 7 };

// A 2D T#. `va` is the surface's base address; `pipe_bank_xor` goes into the low bits of word 0 (tile_swizzle).
struct Image {
    std::uint64_t va = 0;
    std::uint32_t pipe_bank_xor = 0;
    std::uint32_t format = 56;  // GFX10_FORMAT_8_8_8_8_UNORM
    std::uint32_t width = 1, height = 1;
    std::uint32_t sel[4] = {sel_x, sel_y, sel_z, sel_w};
    std::uint32_t base_level = 0, last_level = 0, max_mip = 0;
    std::uint32_t sw_mode = 0;  // SW_LINEAR
    void write(void* at) const
    {
        std::uint32_t w[8] = {};
        w[0] = static_cast<std::uint32_t>(va >> 8) | pipe_bank_xor;
        w[1] = put(static_cast<std::uint32_t>(va >> 40), 0, 7) | put(format, 20, 28) | put(width - 1, 30, 31);
        w[2] = put((width - 1) >> 2, 0, 11) | put(height - 1, 14, 27) | put(1, 31, 31);  // RESOURCE_LEVEL
        w[3] = put(sel[0], 0, 2) | put(sel[1], 3, 5) | put(sel[2], 6, 8) | put(sel[3], 9, 11) |
               put(base_level, 12, 15) | put(last_level, 16, 19) | put(sw_mode, 20, 24) | put(9, 28, 31);  // IMG_2D
        w[5] = put(max_mip, 4, 7) | put(4, 20, 22);  // PERF_MOD 4
        std::memcpy(at, w, sizeof(w));
    }
};

// SQ_TEX_CLAMP.
enum : std::uint32_t { wrap = 0, mirror = 1, clamp_last_texel = 2 };

// A point-filtered S# (MIP_FILTER_POINT, MAX_LOD 15), with the given address modes.
inline void write_sampler(void* at, std::uint32_t u, std::uint32_t v)
{
    const std::uint32_t w[4] = {put(u, 0, 2) | put(v, 3, 5) | put(clamp_last_texel, 6, 8), put(15 << 8, 12, 23),
                                put(1, 26, 27), 0};
    std::memcpy(at, w, sizeof(w));
}

// A raw buffer V# (stride 0, GFX10_FORMAT_32_FLOAT, OOB_SELECT_RAW: offset < num_records).
inline void write_buffer(void* at, std::uint64_t va, std::uint32_t bytes)
{
    const std::uint32_t w[4] = {static_cast<std::uint32_t>(va), put(static_cast<std::uint32_t>(va >> 32), 0, 15), bytes,
                                put(sel_x, 0, 2) | put(sel_y, 3, 5) | put(sel_z, 6, 8) | put(sel_w, 9, 11) |
                                    put(22, 12, 18) | put(1, 24, 24) | put(3, 28, 29)};
    std::memcpy(at, w, sizeof(w));
}

// The console container of d3d12_xs_api.h around one program; a compute container also gets its compute info.
inline std::vector<std::uint8_t> container(X2WShaderStage stage, const std::uint8_t* code, std::size_t bytes,
                                           const std::vector<X2WShaderBinding>& bindings,
                                           const X2WShaderComputeInfo* compute = nullptr)
{
    X2WShaderContainer header{};
    header.magic = X2W_SHADER_CONTAINER_MAGIC;
    header.version = X2W_SHADER_CONTAINER_VERSION;
    header.stage = stage;
    header.binding_count = static_cast<std::uint32_t>(bindings.size());
    header.binding_offset = sizeof(header);
    std::uint32_t at = static_cast<std::uint32_t>(sizeof(header) + bindings.size() * sizeof(X2WShaderBinding));
    if (compute) {
        header.stage_info_offset = at;
        at += sizeof(*compute);
    }
    header.code_offset = at;
    header.code_bytes = static_cast<std::uint32_t>(bytes);
    std::vector<std::uint8_t> out(header.code_offset + bytes);
    std::memcpy(out.data(), &header, sizeof(header));
    if (!bindings.empty()) std::memcpy(out.data() + sizeof(header), bindings.data(), bindings.size() * sizeof(bindings[0]));
    if (compute) std::memcpy(out.data() + header.stage_info_offset, compute, sizeof(*compute));
    std::memcpy(out.data() + header.code_offset, code, bytes);
    return out;
}

}  // namespace r6
