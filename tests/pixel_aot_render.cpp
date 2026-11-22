#include "bvh_fixture.h"
#include "pixel_aot_vs.h"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <iterator>
#include <string_view>

using namespace bvh_fixture;

namespace {
// Includes UNORM values on both sides of a binary16 rounding midpoint.
constexpr std::array<UINT, 8> ramp{0, 16, 37, 64, 101, 153, 219, 254};

D3D12_RESOURCE_DESC texture_desc(UINT width, UINT height, DXGI_FORMAT format, D3D12_RESOURCE_FLAGS flags)
{
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width;
    desc.Height = height;
    desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = format;
    desc.Flags = flags;
    return desc;
}

float expected_channel(UINT byte)
{
    if (!byte) return 0;
    // Fixture inputs are zero or normal positive half values. Truncate the exact
    // UNORM fraction to the 11 significant bits of a binary16 MRT export.
    const double value = byte / 255.0;
    int exponent;
    std::frexp(value, &exponent);
    const double scale = std::ldexp(1.0, 11 - exponent);
    return static_cast<float>(std::floor(value * scale) / scale);
}
using Color = std::array<float, 4>;

// Optional title memory for a case (see docs/experiments.md): ranges in title address order and
// the contents of the buffers they alias, bound for pixel shaders through title_va_lookup.hlsli.
struct TitleRangeRecord {
    UINT64 begin, end;
    UINT slot, reserved;
};
static_assert(sizeof(TitleRangeRecord) == 24);
struct TitleMemory {
    std::vector<TitleRangeRecord> ranges;
    std::vector<std::vector<BYTE>> slots;
};

struct PixelInput {
    UINT width, height, scale;
    DXGI_FORMAT format;
    std::vector<BYTE> rows;
    std::vector<Color> expected;
    std::vector<BYTE> secondRows;
    std::vector<Word> constants = std::vector<Word>(64);
    TitleMemory memory;
};

struct MipDraw {
    UINT sampledLevel;
    UINT scale;
    UINT requestedMip = 0;
    bool isTailDraw = false;
    bool partialQuad = false;
};

struct Extent {
    UINT width, height;
    Extent mip(UINT level) const {
        return {std::max<UINT>(1, width >> level), std::max<UINT>(1, height >> level)};
    }
};

void draw_verified(ID3D12Device* device, const char* path, const std::vector<PixelInput>& levels,
                   Extent base, UINT firstResident, const std::vector<MipDraw>& draws, const char* capture)
{
    const auto& input = levels.front();
    auto cb = upload(device, input.constants);
    // Title memory is always bound. Without a memory section the range buffer holds one zeroed range
    // and the count is 0, and every slot views the same small zero buffer.
    std::vector<TitleRangeRecord> rangeRecords = input.memory.ranges;
    const UINT rangeCount = static_cast<UINT>(rangeRecords.size());
    if (rangeRecords.empty()) rangeRecords.push_back({});
    auto rangeBuffer = upload(device, rangeRecords);
    const std::vector<BYTE> zeroBytes(16);
    auto zeroBuffer = upload(device, zeroBytes);
    std::array<ComPtr<ID3D12Resource>, 8> slotBuffers;
    std::array<UINT, 8> slotWords{};
    for (size_t i = 0; i < slotBuffers.size(); ++i) {
        if (i < input.memory.slots.size() && !input.memory.slots[i].empty()) {
            slotBuffers[i] = upload(device, input.memory.slots[i]);
            slotWords[i] = static_cast<UINT>(input.memory.slots[i].size() / 4);
        } else {
            slotBuffers[i] = zeroBuffer;
            slotWords[i] = 4;
        }
    }
    std::ifstream file(path, std::ios::binary);
    std::vector<char> ps{std::istreambuf_iterator<char>(file), {}};
    if (ps.empty() || file.bad()) throw std::runtime_error("Cannot read compiled pixel shader");
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0, pixel_aot_vs, sizeof(pixel_aot_vs), IID_PPV_ARGS(&root)), "Pixel root");
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root.Get();
    desc.VS = {pixel_aot_vs, sizeof(pixel_aot_vs)};
    desc.PS = {ps.data(), ps.size()};
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    auto& blend = desc.BlendState.RenderTarget[0];
    blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
    blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
    blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
    blend.LogicOp = D3D12_LOGIC_OP_NOOP;
    blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    desc.SampleMask = UINT_MAX;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.NumRenderTargets = desc.SampleDesc.Count = 1;
    desc.RTVFormats[0] = DXGI_FORMAT_R32G32B32A32_FLOAT;
    ComPtr<ID3D12PipelineState> pso;
    check(device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso)), "Translated pixel pipeline");

    auto srcDesc = texture_desc(base.width, base.height, input.format, D3D12_RESOURCE_FLAG_NONE);
    if (input.format == DXGI_FORMAT_BC7_UNORM && (srcDesc.Width % 4 || srcDesc.Height % 4))
        throw std::runtime_error("Expected block-aligned BC7 base dimensions");
    const UINT residentCount = static_cast<UINT>(levels.size());
    srcDesc.MipLevels = static_cast<UINT16>(firstResident + residentCount);
    auto texture = resource(device, srcDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    const D3D12_CLEAR_VALUE clear{desc.RTVFormats[0], {-1, -1, -1, -1}};
    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> layouts(residentCount);
    UINT64 sourceBytes = 0;
    std::vector<UINT> rows(residentCount);
    std::vector<UINT64> rowBytes(residentCount);
    device->GetCopyableFootprints(&srcDesc, firstResident, residentCount, 0, layouts.data(), rows.data(), rowBytes.data(), &sourceBytes);
    std::vector<BYTE> colors(sourceBytes);
    for (UINT level = 0; level < residentCount; ++level) {
        const auto& packed = levels[level].rows;
        if (rowBytes[level] * rows[level] != packed.size()) throw std::runtime_error("Invalid texture row size");
        for (UINT y = 0; y < rows[level]; ++y) {
            auto offset = layouts[level].Offset + size_t(y) * layouts[level].Footprint.RowPitch;
            std::memcpy(colors.data() + offset, packed.data() + y * rowBytes[level], rowBytes[level]);
        }
    }
    auto staging = upload(device, colors);
    ComPtr<ID3D12Resource> secondTexture, secondStaging;
    if (!input.secondRows.empty()) {
        if (residentCount != 1 || firstResident || input.secondRows.size() != input.rows.size())
            throw std::runtime_error("Invalid second texture extent");
        for (UINT y = 0; y < rows[0]; ++y)
            std::memcpy(colors.data() + y * layouts[0].Footprint.RowPitch,
                        input.secondRows.data() + y * rowBytes[0], rowBytes[0]);
        secondStaging = upload(device, colors);
        secondTexture = resource(device, srcDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    }
    D3D12_DESCRIPTOR_HEAP_DESC heapDesc{};
    heapDesc.NumDescriptors = 1;
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    ComPtr<ID3D12DescriptorHeap> rtvs, srvs;
    check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&rtvs)), "Pixel target heap");
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heapDesc.NumDescriptors = 2 + 8;
    heapDesc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&srvs)), "Pixel texture heap");
    const auto rtv = rtvs->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC view{};
    view.Format = input.format;
    view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    view.Texture2D.MostDetailedMip = firstResident;
    view.Texture2D.MipLevels = residentCount;
    device->CreateShaderResourceView(texture.Get(), &view, srvs->GetCPUDescriptorHandleForHeapStart());
    auto secondHandle = srvs->GetCPUDescriptorHandleForHeapStart();
    secondHandle.ptr += device->GetDescriptorHandleIncrementSize(heapDesc.Type);
    device->CreateShaderResourceView(secondTexture.Get(), &view, secondHandle);
    const UINT increment = device->GetDescriptorHandleIncrementSize(heapDesc.Type);
    for (UINT i = 0; i < 8; ++i) {
        D3D12_SHADER_RESOURCE_VIEW_DESC raw{};
        raw.Format = DXGI_FORMAT_R32_TYPELESS;
        raw.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        raw.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        raw.Buffer.NumElements = slotWords[i];
        raw.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        auto handle = srvs->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(2 + i) * increment;
        device->CreateShaderResourceView(slotBuffers[i].Get(), &raw, handle);
    }

    bool textureUploaded = false;
    for (const auto& req : draws) {
        if (req.isTailDraw)
            std::printf("requested_mip=%u sampled_mip=%u ", req.requestedMip, req.sampledLevel + firstResident);
        const auto& sampled = levels.at(req.sampledLevel);
        ComPtr<ID3D12Resource> partialTriangle;
        if (req.partialQuad)
            partialTriangle = upload(device, std::vector<Word>{3, 4, 5});
        const auto [width, height] = req.isTailDraw ? base.mip(req.requestedMip)
                                                   : Extent{sampled.width * req.scale, sampled.height * req.scale};
        auto dstDesc = texture_desc(width, height, desc.RTVFormats[0], D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        auto target = resource(device, dstDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_RENDER_TARGET, &clear);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT resultLayout{};
        UINT64 resultBytes = 0;
        device->GetCopyableFootprints(&dstDesc, 0, 1, 0, &resultLayout, nullptr, nullptr, &resultBytes);
        auto back = make_buffer(device, resultBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        device->CreateRenderTargetView(target.Get(), nullptr, rtv);
        ComputeCommands cmd(device, pso.Get(), D3D12_COMMAND_LIST_TYPE_DIRECT);
        auto* list = cmd.list.Get();
        D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
        if (!textureUploaded) {
            src.pResource = staging.Get();
            src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            dst.pResource = texture.Get();
            dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            for (UINT level = 0; level < residentCount; ++level) {
                src.PlacedFootprint = layouts[level];
                dst.SubresourceIndex = firstResident + level;
                list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            }
            transition(list, texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            if (secondTexture) {
                src.pResource = secondStaging.Get();
                dst.pResource = secondTexture.Get();
                list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
                transition(list, secondTexture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            }
            textureUploaded = true;
        }
        ID3D12DescriptorHeap* heaps[]{srvs.Get()};
        list->SetDescriptorHeaps(1, heaps);
        list->SetGraphicsRootSignature(root.Get());
        list->SetGraphicsRootDescriptorTable(0, srvs->GetGPUDescriptorHandleForHeapStart());
        list->SetGraphicsRootConstantBufferView(1, cb->GetGPUVirtualAddress());
        list->SetGraphicsRootShaderResourceView(2, rangeBuffer->GetGPUVirtualAddress());
        auto memoryTable = srvs->GetGPUDescriptorHandleForHeapStart();
        memoryTable.ptr += UINT64(2) * increment;
        list->SetGraphicsRootDescriptorTable(3, memoryTable);
        list->SetGraphicsRoot32BitConstants(4, 1, &rangeCount, 0);
        // WARP and hardware can use either the rounded SRV extent or the
        // unrounded base extent for implicit LOD. Their geometric mean is
        // within half a mip of both, since rounding discards less than one texel.
        const auto viewportAxis = [&](UINT target, UINT resident, UINT baseAxis) {
            const float unrounded = std::ldexp(float(baseAxis), -static_cast<int>(firstResident));
            const float span = std::sqrt(resident * (std::max)(1.0f, unrounded));
            return (std::max)(float(target), std::ldexp(span, -static_cast<int>(req.sampledLevel)));
        };
        const float viewportWidth = viewportAxis(width, input.width, base.width);
        const float viewportHeight = viewportAxis(height, input.height, base.height);
        const D3D12_VIEWPORT viewport{(width - viewportWidth) * 0.5f, (height - viewportHeight) * 0.5f,
                                      viewportWidth, viewportHeight, 0, 1};
        const D3D12_RECT scissor{0,0,LONG(width),LONG(height)};
        list->RSSetViewports(1, &viewport);
        list->RSSetScissorRects(1, &scissor);
        list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        list->ClearRenderTargetView(rtv, clear.Color, 0, nullptr);
        list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        if (partialTriangle) {
            const D3D12_INDEX_BUFFER_VIEW indices{partialTriangle->GetGPUVirtualAddress(),
                                                   3 * sizeof(Word), DXGI_FORMAT_R32_UINT};
            list->IASetIndexBuffer(&indices);
            list->DrawIndexedInstanced(3, 1, 0, 0, 0);
        } else {
            list->DrawInstanced(3,1,0,0);
        }
        transition(list, target.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        src.pResource = target.Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.SubresourceIndex = 0;
        dst.pResource = back.Get();
        dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint = resultLayout;
        list->CopyTextureRegion(&dst, 0,0,0, &src, nullptr);
        cmd.submit_and_wait(device);
        auto words = read(back.Get(), resultBytes/4);
        std::vector<BYTE> image;
        if (capture) image.reserve(size_t(width) * height * 4);
        for (UINT y = 0; y < height; ++y) {
            const UINT numeratorY = (2 * y + 1) * sampled.height;
            const UINT sampleY = numeratorY / (2 * height);
            for (UINT x = 0; x < width; ++x) {
                const UINT numeratorX = (2 * x + 1) * sampled.width;
                const UINT sampleX = numeratorX / (2 * width);
                const auto& expected = sampled.expected[sampleY * sampled.width + sampleX];
                const auto offset = y * resultLayout.Footprint.RowPitch / 4 + x * 4;
                Color actual;
                std::memcpy(actual.data(), words.data() + offset, sizeof(actual));
                const auto matches = [&](const Color& ref) {
                    return std::memcmp(actual.data(), ref.data(), sizeof(actual)) == 0;
                };
                bool matched = matches(expected);
                // The exact texel is always tried first. Neighbors are admitted only
                // for magnified tail draws, which sample through the root signature's
                // single static sampler (MIN_MAG_MIP_POINT, clamp addressing).
                if (!matched && req.isTailDraw && req.scale > 1) {
                    // Per axis, at most one immediate neighbor in the same mip:
                    // the previous texel for a center exactly on a boundary, or
                    // the next texel for a center up to 1/512 texel below a
                    // boundary (tie included), where rounding the scaled
                    // coordinate to 8 fractional bits crosses it. The last texel
                    // has no boundary above it under clamp addressing.
                    const auto neighbor = [](UINT numerator, UINT denominator, UINT sample, UINT extent) {
                        const UINT remainder = numerator % denominator;
                        if (!remainder) return sample - 1;
                        const bool roundsUp = UINT64(remainder) * 512 >= UINT64(denominator) * 511;
                        return roundsUp && sample + 1 < extent ? sample + 1 : sample;
                    };
                    const UINT nearX = neighbor(numeratorX, 2 * width, sampleX, sampled.width);
                    const UINT nearY = neighbor(numeratorY, 2 * height, sampleY, sampled.height);
                    // Each candidate must match as a whole RGBA texel.
                    matched = matches(sampled.expected[sampleY * sampled.width + nearX]) ||
                              matches(sampled.expected[nearY * sampled.width + sampleX]) ||
                              matches(sampled.expected[nearY * sampled.width + nearX]);
                }
                if (!matched) {
                    std::fprintf(stderr, "pixel_mismatch x=%u y=%u\n", x, y);
                    for (size_t c = 0; c < actual.size(); ++c)
                        std::fprintf(stderr, "channel=%zu expected=%g actual=%g\n", c, expected[c], actual[c]);
                    throw std::runtime_error("AOT color export differs from CPU reference");
                }
                if (capture) {
                    for (float value : actual) image.push_back(static_cast<BYTE>(std::lround(value * 255)));
                }
            }
        }
        if (capture) {
            std::ofstream output(capture, std::ios::binary);
            output.write(reinterpret_cast<const char*>(image.data()), image.size());
            output.close();
            if (!output) throw std::runtime_error("Cannot save GPU readback");
        }
        std::printf("pixels=%u channels=%u max_absolute_error=0\n", width * height, width * height * 4);
    }
}

void draw_verified(ID3D12Device* device, const char* path, const std::vector<PixelInput>& levels,
                   UINT firstResident, UINT sampledLevel, const char* capture)
{
    const auto& top = levels.front();
    draw_verified(device, path, levels, {top.width << firstResident, top.height << firstResident},
                  firstResident, {{sampledLevel, levels.at(sampledLevel).scale}}, capture);
}
}

namespace {
// Memory section after the 1280-byte case: magic 'X2WM', range count (0..8), slot count (0..8), a zero
// word, the ranges (begin and end as u64, slot, zero word) and then each slot as a byte size and its bytes.
TitleMemory parse_memory_section(const char* data, size_t size)
{
    size_t at = 0;
    const auto word = [&](const char* what) {
        if (size - at < 4) throw BadCase(std::string("Memory section is truncated at ") + what);
        UINT value;
        std::memcpy(&value, data + at, 4);
        at += 4;
        return value;
    };
    if (word("magic") != 0x4d573258u) throw BadCase("Memory section has the wrong magic");
    const UINT rangeCount = word("range count"), slotCount = word("slot count");
    if (rangeCount > 8 || slotCount > 8) throw BadCase("Memory section has more than 8 ranges or slots");
    if (word("reserved") != 0) throw BadCase("Memory section reserved word is not zero");
    TitleMemory memory;
    for (UINT i = 0; i < rangeCount; ++i) {
        if (size - at < sizeof(TitleRangeRecord)) throw BadCase("Memory section is truncated in the ranges");
        TitleRangeRecord range;
        std::memcpy(&range, data + at, sizeof(range));
        at += sizeof(range);
        memory.ranges.push_back(range);
    }
    for (UINT i = 0; i < slotCount; ++i) {
        const UINT bytes = word("slot size");
        if (bytes % 4 || bytes > (1u << 20)) throw BadCase("Memory slot size is not a multiple of 4 or exceeds 1 MiB");
        if (size - at < bytes) throw BadCase("Memory section is truncated in a slot");
        memory.slots.emplace_back(data + at, data + at + bytes);
        at += bytes;
    }
    if (at != size) throw BadCase("Memory section has trailing bytes");
    for (size_t i = 0; i < memory.ranges.size(); ++i) {
        const auto& range = memory.ranges[i];
        if (range.reserved != 0) throw BadCase("Memory range reserved word is not zero");
        if (range.begin % 4 || range.begin >= range.end)
            throw BadCase("Memory range is empty, reversed or not 4-byte aligned");
        if (range.end - range.begin >= (UINT64(1) << 32)) throw BadCase("Memory range is 4 GiB or larger");
        if (range.slot >= slotCount) throw BadCase("Memory range names a slot that does not exist");
        if (range.end - range.begin > memory.slots[range.slot].size())
            throw BadCase("Memory range is larger than its slot");
        if (i && memory.ranges[i - 1].end > range.begin)
            throw BadCase("Memory ranges are unsorted or overlap");
    }
    return memory;
}
}

void check_translated_pixel(ID3D12Device* device, const char* path, bool swapRB, const char* reference)
{
    PixelInput input{8, 8, 8, DXGI_FORMAT_R8G8B8A8_UNORM};
    for (auto g : ramp) {
        for (auto r : ramp) {
            input.rows.insert(input.rows.end(), {BYTE(r), BYTE(g), 128, 255});
            Color expected{expected_channel(r), expected_channel(g), expected_channel(128), 1};
            if (swapRB) std::swap(expected[0], expected[2]);
            input.expected.push_back(expected);
        }
    }
    if (reference) {
        std::ifstream file(reference, std::ios::binary);
        const std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
        constexpr size_t fixed = 64 * sizeof(Word) + 64 * sizeof(Color);
        if (file.bad() || bytes.size() < fixed)
            throw BadCase("Expected a 256-byte constant buffer and 64 float4 reference colors");
        std::memcpy(input.constants.data(), bytes.data(), input.constants.size() * sizeof(Word));
        std::memcpy(input.expected.data(), bytes.data() + input.constants.size() * sizeof(Word),
                    input.expected.size() * sizeof(Color));
        if (bytes.size() > fixed) input.memory = parse_memory_section(bytes.data() + fixed, bytes.size() - fixed);
    }
    std::vector<PixelInput> levels;
    levels.push_back(std::move(input));
    draw_verified(device, path, levels, 0, 0, nullptr);
}

// The mip-chain fixture of --check-pixel-case-mips (mirrored by mip_texel in tests/pixel_aot_draws/image.py): an 8x8
// R8G8B8A8 texture with all four levels. Texel (x, y) of level k is (ramp[(x + 2k) % 8], ramp[(y + 5k) % 8], blue[k], 255),
// where level 0 is read in 2x2 blocks (x and y halved first), so that a level-0 read at the 4x4 draw's pixel centers,
// which fall on level-0 texel edges, has one value. The draw is 4x4 pixels over the 8x8 base, so the implicit level is
// exactly 1, and the case holds the 256-byte constant buffer and 16 reference colors, one per pixel in row order.
void check_translated_pixel_mips(ID3D12Device* device, const char* path, const char* reference)
{
    constexpr std::array<UINT, 4> blue{128, 64, 219, 37};
    std::vector<PixelInput> levels;
    for (UINT level = 0; level < 4; ++level) {
        const UINT size = 8u >> level;
        PixelInput input{size, size, 1, DXGI_FORMAT_R8G8B8A8_UNORM};
        for (UINT y = 0; y < size; ++y) {
            for (UINT x = 0; x < size; ++x) {
                const UINT u = level ? x : x / 2, v = level ? y : y / 2;
                input.rows.insert(input.rows.end(), {BYTE(ramp[(u + 2 * level) % 8]), BYTE(ramp[(v + 5 * level) % 8]),
                                                     BYTE(blue[level]), 255});
            }
        }
        levels.push_back(std::move(input));
    }
    std::ifstream file(reference, std::ios::binary);
    const std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
    constexpr size_t fixed = 64 * sizeof(Word) + 16 * sizeof(Color);
    if (file.bad() || bytes.size() != fixed)
        throw BadCase("Expected a 256-byte constant buffer and 16 float4 reference colors");
    std::memcpy(levels[0].constants.data(), bytes.data(), levels[0].constants.size() * sizeof(Word));
    levels[1].expected.resize(16);
    std::memcpy(levels[1].expected.data(), bytes.data() + levels[0].constants.size() * sizeof(Word), 16 * sizeof(Color));
    draw_verified(device, path, levels, {8, 8}, 0, {{1, 1}}, nullptr);
}

void check_pixel_quad_lod(ID3D12Device* device, const char* shader)
{
    PixelInput top{8, 8, 1, DXGI_FORMAT_R8G8B8A8_UNORM};
    PixelInput next{4, 4, 1, DXGI_FORMAT_R8G8B8A8_UNORM};
    const float scale = 4.0f;
    std::memcpy(&top.constants[2], &scale, sizeof(scale));
    for (UINT y = 0; y < top.height; ++y) {
        for (UINT x = 0; x < top.width; ++x) {
            top.rows.insert(top.rows.end(), {255, 0, 0, 255});
            // Pixel centers have x + y + 1 below the triangle's 7.75-pixel edge.
            top.expected.push_back(x + y <= 6 ? Color{0, 1, 0, 1} : Color{-1, -1, -1, -1});
        }
    }
    for (UINT texel = 0; texel < next.width * next.height; ++texel)
        next.rows.insert(next.rows.end(), {0, 255, 0, 255});
    MipDraw draw{0, 1};
    draw.partialQuad = true;
    draw_verified(device, shader, {std::move(top), std::move(next)}, {8, 8}, 0, {draw}, nullptr);
}

void check_dual_pixel(ID3D12Device* device, const char* shader, const char* capture, bool swap)
{
    PixelInput input{8, 8, 8, DXGI_FORMAT_R8G8B8A8_UNORM};
    for (auto blue : ramp) {
        for (auto red : ramp) {
            input.rows.insert(input.rows.end(), {BYTE(red), 0, 0, 255});
            input.secondRows.insert(input.secondRows.end(), {0, 0, BYTE(blue), 255});
            // The two nonzero channels use exact power-of-two scaling after UNORM conversion.
            input.expected.push_back({expected_channel(red * 3) / 4, 0, expected_channel(blue) / 4, 1});
        }
    }
    if (swap) std::swap(input.rows, input.secondRows);
    draw_verified(device, shader, {input}, 0, 0, capture);
}

namespace {
PixelInput read_bc7_case(const char* fixture)
{
    std::ifstream file(fixture, std::ios::binary);
    std::array<char,4> magic{};
    UINT w = 0, h = 0;
    file.read(magic.data(), 4);
    file.read(reinterpret_cast<char*>(&w), sizeof(w));
    file.read(reinterpret_cast<char*>(&h), sizeof(h));
    if (!file || std::memcmp(magic.data(), "BC7C", 4) || !w || !h ||
        w > 4096 || h > 4096 || size_t(w) * h > 4 * 1024 * 1024)
        throw std::runtime_error("Invalid single-level BC7 case dimensions or header");
    PixelInput input{w, h, 1, DXGI_FORMAT_BC7_UNORM};
    const size_t pixels = size_t(w) * h;
    input.rows.resize(((w + 3) / 4) * ((h + 3) / 4) * 16);
    file.read(reinterpret_cast<char*>(input.rows.data()), input.rows.size());
    std::vector<std::array<BYTE,4>> reference(pixels);
    file.read(reinterpret_cast<char*>(reference.data()), pixels * 4);
    if (!file || file.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("BC7 block rows or RGBA reference have incorrect size");
    input.expected.reserve(pixels);
    for (const auto& rgba : reference) {
        input.expected.push_back({expected_channel(rgba[0]), expected_channel(rgba[1]),
                                  expected_channel(rgba[2]), expected_channel(rgba[3])});
    }
    return input;
}

bool is_next_mip(const PixelInput& upper, const PixelInput& lower)
{
    return (upper.width > 1 || upper.height > 1) &&
           lower.width == std::max<UINT>(1, upper.width / 2) &&
           lower.height == std::max<UINT>(1, upper.height / 2);
}
}

void check_bc7_pixel(ID3D12Device* device, const char* shader, const char* fixture,
                     const char* capture, const char* mip1)
{
    std::vector<PixelInput> levels;
    levels.push_back(read_bc7_case(fixture));
    if (mip1) {
        auto lower = read_bc7_case(mip1);
        if (!is_next_mip(levels.front(), lower))
            throw std::runtime_error("Expected a half-size BC7 mip");
        levels.push_back(std::move(lower));
    }
    draw_verified(device, shader, levels, 0, static_cast<UINT>(levels.size() - 1), capture);
}

void check_bc7_tail(ID3D12Device* device, const char* shader, const char* firstMip, int count, char** paths)
{
    const std::string_view arg(firstMip);
    UINT first = 0;
    const auto parsed = std::from_chars(arg.data(), arg.data() + arg.size(), first);
    if (parsed.ec != std::errc{} || parsed.ptr != arg.data() + arg.size() || first > 12)
        throw std::runtime_error("Invalid first resident mip");
    Extent base{};
    const bool explicitBase = count > 0 && std::string_view(paths[0]) == "--base-size";
    if (explicitBase) {
        if (count < 4) throw std::runtime_error("Expected --base-size WIDTH HEIGHT followed by BC7 cases");
        const auto dimension = [](std::string_view text) -> UINT {
            UINT value = 0;
            const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
            if (result.ec != std::errc{} || result.ptr != text.data() + text.size() || !value)
                throw std::runtime_error("Invalid BC7 base dimension");
            return value;
        };
        base = {dimension(paths[1]), dimension(paths[2])};
        paths += 3;
        count -= 3;
    }
    std::vector<PixelInput> levels;
    for (int i = 0; i < count; ++i) {
        auto level = read_bc7_case(paths[i]);
        if (levels.empty()) {
            if (!explicitBase) base = {level.width << first, level.height << first};
            if (base.width > 4096 || base.height > 4096 || UINT64(base.width) * base.height > 4 * 1024 * 1024)
                throw std::runtime_error("Logical BC7 texture exceeds fixture bounds");
            const auto resident = base.mip(first);
            if (!(std::max<UINT>(base.width, base.height) >> first) ||
                resident.width != level.width || resident.height != level.height)
                throw std::runtime_error("BC7 base size is incompatible with the first resident mip");
        } else if (!is_next_mip(levels.back(), level)) {
            throw std::runtime_error("Expected consecutive BC7 mip sizes");
        }
        levels.push_back(std::move(level));
    }
    // Changing the viewport exercises the copy shader's implicit LOD with the same SRV range.
    std::vector<MipDraw> draws;
    for (UINT mip = 0; mip < first + levels.size(); ++mip) {
        const UINT scale = mip < first ? 1u << (first - mip) : 1u;
        const UINT selected = mip < first ? 0 : mip - first;
        draws.push_back({selected, scale, mip, true});
    }
    draw_verified(device, shader, levels, base, first, draws, nullptr);
}
