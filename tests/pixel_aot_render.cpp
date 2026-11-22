#include "bvh_fixture.h"
#include "desktop_gpu.h"
#include "pixel_aot_vs.h"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <iterator>
#include <optional>
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
// A storage image of a case (the 'X2WI' part of the memory section, see parse_memory_section): an R32_UINT (one channel)
// or R32G32B32A32_UINT (four) texture with its levels, bound as one UAV per level at u(8 * slot + level), space2, and
// compared word for word after the single draw.
struct StorageImage {
    UINT slot, channels, width, height, levels;
    std::vector<BYTE> initial, expected;  // every level in order, rows packed, 4 * channels bytes per texel
};
struct TitleMemory {
    std::vector<TitleRangeRecord> ranges;
    std::vector<std::vector<BYTE>> slots;
    // When not empty: each slot's contents after the draw, compared byte for byte (a case that checks shader writes).
    std::vector<std::vector<BYTE>> expected;
    // Storage images written by the shader (a case that checks image writes), in ascending slot order.
    std::vector<StorageImage> images;
};

struct PixelInput {
    UINT width, height, scale;
    DXGI_FORMAT format;
    std::vector<BYTE> rows;
    std::vector<Color> expected;
    std::vector<BYTE> secondRows;
    std::vector<Word> constants = std::vector<Word>(64);
    TitleMemory memory;
    bool integerRT = false;      // bit 0 of the flags word of the optional 'X2WF' case section
    std::vector<BYTE> nanMask;   // 64 per-texel NaN-class mask bytes, empty without that section
    UINT8 writeMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    std::vector<BYTE> coverage;
    // An explicit viewport (upstream's case trailer, flags bit 1); one reference color per target pixel.
    std::optional<D3D12_VIEWPORT> viewport;
};

// The outputs of a --check-pixel-outputs draw: R32G32B32A32_FLOAT targets 0..N-1, each cleared to -1 and drawn with
// its own write mask (D3D12_COLOR_WRITE_ENABLE bits, R = 1 .. A = 8, as the export's component mask), and optionally
// a D32_FLOAT depth target cleared to 1 and written with the depth test always passing. Every target and the depth
// are read back and compared bit-exactly with one reference per texel.
struct PixelOutputs {
    std::vector<UINT> masks;
    std::vector<std::vector<Color>> expected;
    bool depth = false;
    std::vector<float> expectedDepth;
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
                   Extent base, UINT firstResident, const std::vector<MipDraw>& draws, const char* capture,
                   const PixelOutputs* outputs = nullptr, ID3D12Resource* gpuConstants = nullptr)
{
    constexpr DXGI_FORMAT targetFormat = DXGI_FORMAT_R32G32B32A32_FLOAT;
    const UINT targetCount = outputs ? static_cast<UINT>(outputs->masks.size()) : 1;
    const bool depth = outputs && outputs->depth;
    const auto& input = levels.front();
    ComPtr<ID3D12Resource> uploadedConstants;
    if (!gpuConstants) {
        uploadedConstants = upload(device, input.constants);
        gpuConstants = uploadedConstants.Get();
    }
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
    // A case with expected memory checks what the shader writes: each slot with data gets a writable copy, bound as
    // RWByteAddressBuffer (u0, space1; root parameter 5) and compared after the single draw. Otherwise that table
    // holds null views.
    const auto& expectedMemory = input.memory.expected;
    const bool checksWrites = !expectedMemory.empty();
    if (checksWrites && draws.size() != 1) throw std::runtime_error("A title memory write check needs exactly one draw");
    std::array<ComPtr<ID3D12Resource>, 8> writable;
    for (size_t i = 0; checksWrites && i < input.memory.slots.size(); ++i) {
        if (!input.memory.slots[i].empty())
            writable[i] = make_buffer(device, input.memory.slots[i].size(), D3D12_HEAP_TYPE_DEFAULT,
                                      D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    }
    // Storage images: each gets a default-heap texture with all its levels and one UAV per level in the image table
    // (root parameter 6: u0..u31 in space2, eight per slot, null views elsewhere), and is compared after the single draw.
    const auto& images = input.memory.images;
    if (!images.empty() && draws.size() != 1) throw std::runtime_error("A storage image check needs exactly one draw");
    struct ImageResources {
        ComPtr<ID3D12Resource> texture, staging, back;
        std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> layouts;
        std::vector<UINT> rows;
        std::vector<UINT64> rowBytes;
        UINT64 bytes = 0;
    };
    const auto imageFormat = [](UINT channels) {
        return channels == 1 ? DXGI_FORMAT_R32_UINT : DXGI_FORMAT_R32G32B32A32_UINT;
    };
    std::vector<ImageResources> imageResources(images.size());
    for (size_t n = 0; n < images.size(); ++n) {
        const auto& image = images[n];
        auto& res = imageResources[n];
        auto imageDesc = texture_desc(image.width, image.height, imageFormat(image.channels),
                                      D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        imageDesc.MipLevels = static_cast<UINT16>(image.levels);
        res.texture = resource(device, imageDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
        res.layouts.resize(image.levels);
        res.rows.resize(image.levels);
        res.rowBytes.resize(image.levels);
        device->GetCopyableFootprints(&imageDesc, 0, image.levels, 0, res.layouts.data(), res.rows.data(),
                                      res.rowBytes.data(), &res.bytes);
        std::vector<BYTE> staged(res.bytes);
        size_t at = 0;
        for (UINT level = 0; level < image.levels; ++level) {
            for (UINT y = 0; y < res.rows[level]; ++y) {
                if (image.initial.size() - at < res.rowBytes[level]) throw std::runtime_error("Invalid storage image size");
                std::memcpy(staged.data() + res.layouts[level].Offset + size_t(y) * res.layouts[level].Footprint.RowPitch,
                            image.initial.data() + at, res.rowBytes[level]);
                at += res.rowBytes[level];
            }
        }
        if (at != image.initial.size() || at != image.expected.size()) throw std::runtime_error("Invalid storage image size");
        res.staging = upload(device, staged);
        res.back = make_buffer(device, res.bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
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
    desc.BlendState.IndependentBlendEnable = outputs != nullptr;
    for (UINT t = 0; t < targetCount; ++t) {
        auto& blend = desc.BlendState.RenderTarget[t];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = static_cast<UINT8>(outputs ? outputs->masks[t] : input.writeMask);
        desc.RTVFormats[t] = targetFormat;
    }
    desc.SampleMask = UINT_MAX;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.NumRenderTargets = targetCount;
    desc.SampleDesc.Count = 1;
    // The integer-export cases (the 'X2WF' flags word) return uint4 from main, so the pipeline's target is R32G32B32A32_UINT.
    if (!outputs && input.integerRT) desc.RTVFormats[0] = DXGI_FORMAT_R32G32B32A32_UINT;
    if (depth) {
        desc.DSVFormat = DXGI_FORMAT_D32_FLOAT;
        desc.DepthStencilState.DepthEnable = TRUE;
        desc.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ALL;
        desc.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    }
    ComPtr<ID3D12PipelineState> pso;
    check(device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso)), "Translated pixel pipeline");

    auto srcDesc = texture_desc(base.width, base.height, input.format, D3D12_RESOURCE_FLAG_NONE);
    if (input.format == DXGI_FORMAT_BC7_UNORM && (srcDesc.Width % 4 || srcDesc.Height % 4))
        throw std::runtime_error("Expected block-aligned BC7 base dimensions");
    const UINT residentCount = static_cast<UINT>(levels.size());
    srcDesc.MipLevels = static_cast<UINT16>(firstResident + residentCount);
    auto texture = resource(device, srcDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    const D3D12_CLEAR_VALUE clear{targetFormat, {-1, -1, -1, -1}};
    D3D12_CLEAR_VALUE depthClear{DXGI_FORMAT_D32_FLOAT};
    depthClear.DepthStencil.Depth = 1;
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
    heapDesc.NumDescriptors = (std::max)(targetCount, 1u);
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    ComPtr<ID3D12DescriptorHeap> rtvs, srvs, dsvs;
    check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&rtvs)), "Pixel target heap");
    const UINT rtvIncrement = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    if (depth) {
        heapDesc.NumDescriptors = 1;
        heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
        check(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&dsvs)), "Pixel depth heap");
    }
    heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heapDesc.NumDescriptors = 2 + 8 + 8 + 32;
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
    for (UINT i = 0; i < 8; ++i) {
        D3D12_UNORDERED_ACCESS_VIEW_DESC rw{};
        rw.Format = DXGI_FORMAT_R32_TYPELESS;
        rw.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        rw.Buffer.NumElements = writable[i] ? slotWords[i] : 4;
        rw.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        auto handle = srvs->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(2 + 8 + i) * increment;
        device->CreateUnorderedAccessView(writable[i].Get(), nullptr, &rw, handle);
    }
    for (UINT d = 0; d < 32; ++d) {
        const UINT slot = d / 8, level = d % 8;
        const auto found = std::find_if(images.begin(), images.end(),
                                        [&](const StorageImage& image) { return image.slot == slot; });
        D3D12_UNORDERED_ACCESS_VIEW_DESC view2d{};
        view2d.Format = found == images.end() ? DXGI_FORMAT_R32_UINT : imageFormat(found->channels);
        view2d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        ID3D12Resource* viewed = nullptr;
        if (found != images.end() && level < found->levels) {
            viewed = imageResources[size_t(found - images.begin())].texture.Get();
            view2d.Texture2D.MipSlice = level;
        }
        auto handle = srvs->GetCPUDescriptorHandleForHeapStart();
        handle.ptr += size_t(2 + 8 + 8 + d) * increment;
        device->CreateUnorderedAccessView(viewed, nullptr, &view2d, handle);
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
        auto dstDesc = texture_desc(width, height, targetFormat, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT resultLayout{};
        UINT64 resultBytes = 0;
        device->GetCopyableFootprints(&dstDesc, 0, 1, 0, &resultLayout, nullptr, nullptr, &resultBytes);
        std::vector<ComPtr<ID3D12Resource>> targets(targetCount), backs(targetCount);
        for (UINT t = 0; t < targetCount; ++t) {
            targets[t] = resource(device, dstDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_RENDER_TARGET, &clear);
            backs[t] = make_buffer(device, resultBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
            auto handle = rtv;
            handle.ptr += size_t(t) * rtvIncrement;
            device->CreateRenderTargetView(targets[t].Get(), nullptr, handle);
        }
        auto depthDesc = texture_desc(width, height, DXGI_FORMAT_D32_FLOAT, D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT depthLayout{};
        UINT64 depthBytes = 0;
        ComPtr<ID3D12Resource> depthTarget, depthBack;
        D3D12_CPU_DESCRIPTOR_HANDLE dsv{};
        if (depth) {
            device->GetCopyableFootprints(&depthDesc, 0, 1, 0, &depthLayout, nullptr, nullptr, &depthBytes);
            depthTarget = resource(device, depthDesc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_DEPTH_WRITE, &depthClear);
            depthBack = make_buffer(device, depthBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
            dsv = dsvs->GetCPUDescriptorHandleForHeapStart();
            device->CreateDepthStencilView(depthTarget.Get(), nullptr, dsv);
        }
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
            for (size_t i = 0; i < writable.size(); ++i) {
                if (!writable[i]) continue;
                transition(list, writable[i].Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
                list->CopyBufferRegion(writable[i].Get(), 0, slotBuffers[i].Get(), 0, input.memory.slots[i].size());
                transition(list, writable[i].Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            }
            for (size_t n = 0; n < images.size(); ++n) {
                const auto& res = imageResources[n];
                src.pResource = res.staging.Get();
                src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
                dst.pResource = res.texture.Get();
                dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                for (UINT level = 0; level < images[n].levels; ++level) {
                    src.PlacedFootprint = res.layouts[level];
                    dst.SubresourceIndex = level;
                    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
                }
                transition(list, res.texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            }
            textureUploaded = true;
        }
        ID3D12DescriptorHeap* heaps[]{srvs.Get()};
        list->SetDescriptorHeaps(1, heaps);
        list->SetGraphicsRootSignature(root.Get());
        list->SetGraphicsRootDescriptorTable(0, srvs->GetGPUDescriptorHandleForHeapStart());
        list->SetGraphicsRootConstantBufferView(1, gpuConstants->GetGPUVirtualAddress());
        list->SetGraphicsRootShaderResourceView(2, rangeBuffer->GetGPUVirtualAddress());
        auto memoryTable = srvs->GetGPUDescriptorHandleForHeapStart();
        memoryTable.ptr += UINT64(2) * increment;
        list->SetGraphicsRootDescriptorTable(3, memoryTable);
        list->SetGraphicsRoot32BitConstants(4, 1, &rangeCount, 0);
        auto writeTable = srvs->GetGPUDescriptorHandleForHeapStart();
        writeTable.ptr += UINT64(2 + 8) * increment;
        list->SetGraphicsRootDescriptorTable(5, writeTable);
        auto imageTable = srvs->GetGPUDescriptorHandleForHeapStart();
        imageTable.ptr += UINT64(2 + 8 + 8) * increment;
        list->SetGraphicsRootDescriptorTable(6, imageTable);
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
        const D3D12_VIEWPORT viewport = input.viewport.value_or(
            D3D12_VIEWPORT{(width - viewportWidth) * 0.5f, (height - viewportHeight) * 0.5f,
                           viewportWidth, viewportHeight, 0, 1});
        const D3D12_RECT scissor{0,0,LONG(width),LONG(height)};
        list->RSSetViewports(1, &viewport);
        list->RSSetScissorRects(1, &scissor);
        // The descriptors of the targets are consecutive in the heap, so one handle names them all.
        list->OMSetRenderTargets(targetCount, targetCount ? &rtv : nullptr, TRUE, depth ? &dsv : nullptr);
        for (UINT t = 0; t < targetCount; ++t) {
            auto handle = rtv;
            handle.ptr += size_t(t) * rtvIncrement;
            list->ClearRenderTargetView(handle, clear.Color, 0, nullptr);
        }
        if (depth) list->ClearDepthStencilView(dsv, D3D12_CLEAR_FLAG_DEPTH, depthClear.DepthStencil.Depth, 0, 0, nullptr);
        list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        ComPtr<ID3D12QueryHeap> queries;
        ComPtr<ID3D12Resource> queryResults;
        if (!input.coverage.empty()) {
            const UINT pixels = width * height;
            if (pixels != input.coverage.size()) throw std::runtime_error("Coverage reference extent");
            D3D12_QUERY_HEAP_DESC queryDesc{D3D12_QUERY_HEAP_TYPE_OCCLUSION, pixels + 1, 0};
            check(device->CreateQueryHeap(&queryDesc, IID_PPV_ARGS(&queries)), "Coverage queries");
            queryResults = make_buffer(device, (pixels + 1) * sizeof(UINT64), D3D12_HEAP_TYPE_READBACK,
                                       D3D12_RESOURCE_STATE_COPY_DEST);
            // First measure a full draw with neighboring lanes active, then locate
            // each surviving sample with a one-pixel scissor.
            for (UINT i = 0; i <= pixels; ++i) {
                if (i) {
                    LONG x = (i - 1) % width, y = (i - 1) / width;
                    const D3D12_RECT pixel{x, y, x + 1, y + 1};
                    list->RSSetScissorRects(1, &pixel);
                }
                list->BeginQuery(queries.Get(), D3D12_QUERY_TYPE_OCCLUSION, i);
                list->DrawInstanced(3, 1, 0, 0);
                list->EndQuery(queries.Get(), D3D12_QUERY_TYPE_OCCLUSION, i);
            }
            list->ResolveQueryData(queries.Get(), D3D12_QUERY_TYPE_OCCLUSION, 0, pixels + 1, queryResults.Get(), 0);
        } else if (partialTriangle) {
            const D3D12_INDEX_BUFFER_VIEW indices{partialTriangle->GetGPUVirtualAddress(),
                                                   3 * sizeof(Word), DXGI_FORMAT_R32_UINT};
            list->IASetIndexBuffer(&indices);
            list->DrawIndexedInstanced(3, 1, 0, 0, 0);
        } else {
            list->DrawInstanced(3,1,0,0);
        }
        src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.SubresourceIndex = 0;
        dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        for (UINT t = 0; t < targetCount; ++t) {
            transition(list, targets[t].Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
            src.pResource = targets[t].Get();
            dst.pResource = backs[t].Get();
            dst.PlacedFootprint = resultLayout;
            list->CopyTextureRegion(&dst, 0,0,0, &src, nullptr);
        }
        if (depth) {
            transition(list, depthTarget.Get(), D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_COPY_SOURCE);
            src.pResource = depthTarget.Get();
            dst.pResource = depthBack.Get();
            dst.PlacedFootprint = depthLayout;
            list->CopyTextureRegion(&dst, 0,0,0, &src, nullptr);
        }
        std::array<ComPtr<ID3D12Resource>, 8> memoryBack;
        for (size_t i = 0; i < writable.size(); ++i) {
            if (!writable[i]) continue;
            const UINT64 bytes = input.memory.slots[i].size();
            memoryBack[i] = make_buffer(device, bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
            transition(list, writable[i].Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
            list->CopyBufferRegion(memoryBack[i].Get(), 0, writable[i].Get(), 0, bytes);
        }
        for (size_t n = 0; n < images.size(); ++n) {
            const auto& res = imageResources[n];
            transition(list, res.texture.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION from{}, to{};
            from.pResource = res.texture.Get();
            from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.pResource = res.back.Get();
            to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            for (UINT level = 0; level < images[n].levels; ++level) {
                from.SubresourceIndex = level;
                to.PlacedFootprint = res.layouts[level];
                list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            }
        }
        cmd.submit_and_wait(device);
        for (size_t i = 0; i < memoryBack.size(); ++i) {
            if (!memoryBack[i]) continue;
            const auto& want = expectedMemory[i];
            const auto got = read(memoryBack[i].Get(), want.size() / 4);
            for (size_t w = 0; w < got.size(); ++w) {
                Word wanted;
                std::memcpy(&wanted, want.data() + 4 * w, sizeof(wanted));
                if (got[w] != wanted) {
                    std::fprintf(stderr, "memory_mismatch slot=%zu offset=0x%zx expected=%08x actual=%08x\n",
                                 i, 4 * w, static_cast<unsigned>(wanted), static_cast<unsigned>(got[w]));
                    throw std::runtime_error("Title memory after the draw differs from CPU reference");
                }
            }
        }
        for (size_t n = 0; n < images.size(); ++n) {
            const auto& image = images[n];
            const auto& res = imageResources[n];
            const auto got = read(res.back.Get(), static_cast<size_t>(res.bytes / 4));
            size_t at = 0;
            for (UINT level = 0; level < image.levels; ++level) {
                const UINT rowWords = static_cast<UINT>(res.rowBytes[level] / 4);
                for (UINT y = 0; y < res.rows[level]; ++y) {
                    const size_t first = static_cast<size_t>(
                        (res.layouts[level].Offset + UINT64(y) * res.layouts[level].Footprint.RowPitch) / 4);
                    for (UINT w = 0; w < rowWords; ++w, at += 4) {
                        Word wanted;
                        std::memcpy(&wanted, image.expected.data() + at, sizeof(wanted));
                        if (got[first + w] != wanted) {
                            std::fprintf(stderr, "image_mismatch slot=%u level=%u x=%u y=%u channel=%u expected=%08x actual=%08x\n",
                                         image.slot, level, w / image.channels, y, w % image.channels,
                                         static_cast<unsigned>(wanted), static_cast<unsigned>(got[first + w]));
                            throw std::runtime_error("Storage image after the draw differs from CPU reference");
                        }
                    }
                }
            }
        }
        if (queryResults) {
            auto counts = read(queryResults.Get(), (input.coverage.size() + 1) * 2);
            UINT sum = 0;
            for (size_t i = 0; i < input.coverage.size(); ++i) {
                sum += input.coverage[i];
                if (counts[2*i+2] != input.coverage[i] || counts[2*i+3]) {
                    std::fprintf(stderr, "coverage pixel=%zu expected=%u actual=%u\n", i, unsigned(input.coverage[i]), counts[2*i+2]);
                    throw std::runtime_error("Sample coverage mismatch");
                }
            }
            if (counts[0] != sum || counts[1]) throw std::runtime_error("Full draw coverage mismatch");
            std::printf("covered_samples=%u checked_pixels=%zu\n", sum, input.coverage.size());
        }
        if (outputs) {
            // One reference per texel for every target and the depth; nothing but the exact bits is admitted.
            // Init-captures: C++17 cannot capture the structured bindings width and height themselves.
            const auto texel = [&sampled, w = width, h = height](UINT x, UINT y) {
                return ((2 * y + 1) * sampled.height / (2 * h)) * sampled.width + (2 * x + 1) * sampled.width / (2 * w);
            };
            for (UINT t = 0; t < targetCount; ++t) {
                const auto data = read(backs[t].Get(), resultBytes / 4);
                for (UINT y = 0; y < height; ++y) {
                    for (UINT x = 0; x < width; ++x) {
                        const auto& expected = outputs->expected[t].at(texel(x, y));
                        Color actual;
                        std::memcpy(actual.data(), data.data() + y * resultLayout.Footprint.RowPitch / 4 + x * 4, sizeof(actual));
                        if (std::memcmp(actual.data(), expected.data(), sizeof(actual))) {
                            std::fprintf(stderr, "pixel_mismatch x=%u y=%u target=%u\n", x, y, t);
                            for (size_t c = 0; c < actual.size(); ++c)
                                std::fprintf(stderr, "channel=%zu expected=%a actual=%a\n", c, expected[c], actual[c]);
                            throw std::runtime_error("AOT color export differs from CPU reference");
                        }
                    }
                }
            }
            if (depth) {
                const auto data = read(depthBack.Get(), depthBytes / 4);
                for (UINT y = 0; y < height; ++y) {
                    for (UINT x = 0; x < width; ++x) {
                        const float expected = outputs->expectedDepth.at(texel(x, y));
                        float actual;
                        std::memcpy(&actual, data.data() + y * depthLayout.Footprint.RowPitch / 4 + x, sizeof(actual));
                        if (std::memcmp(&actual, &expected, sizeof(actual))) {
                            std::fprintf(stderr, "pixel_mismatch x=%u y=%u depth expected=%a actual=%a\n", x, y, expected, actual);
                            throw std::runtime_error("AOT depth export differs from CPU reference");
                        }
                    }
                }
            }
            std::printf("pixels=%u targets=%u depth=%u max_absolute_error=0\n", width * height, targetCount, depth ? 1u : 0u);
            continue;
        }
        auto words = read(backs[0].Get(), resultBytes/4);
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
                const auto bits = [](float value) {
                    UINT word;
                    std::memcpy(&word, &value, sizeof(word));
                    return word;
                };
                const auto is_nan_bits = [](UINT word) {
                    return (word & 0x7f800000u) == 0x7f800000u && (word & 0x007fffffu) != 0u;
                };
                // Per-channel compare against one expected texel. Unmasked channels are strict
                // bitwise. A masked channel accepts a NaN against an expected NaN of any sign or
                // payload and still logs both raw words; masking a channel whose expected word is
                // not NaN is a case-format error.
                const auto matches_at = [&](size_t index) {
                    const auto& reference = sampled.expected[index];
                    const BYTE mask = index < sampled.nanMask.size() ? sampled.nanMask[index] : BYTE{0};
                    for (size_t c = 0; c < actual.size(); ++c) {
                        const UINT expected_bits = bits(reference[c]);
                        const UINT actual_bits = bits(actual[c]);
                        if (mask >> c & 1) {
                            if (!is_nan_bits(expected_bits))
                                throw std::runtime_error("NaN-class mask on a channel whose expected word is not NaN");
                            std::printf("nan_class x=%u y=%u ch=%zu expected=%08x actual=%08x\n",
                                        x, y, c, expected_bits, actual_bits);
                            if (!is_nan_bits(actual_bits)) return false;
                        } else if (expected_bits != actual_bits) {
                            return false;
                        }
                    }
                    return true;
                };
                bool matched = matches_at(sampleY * sampled.width + sampleX);
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
                    matched = matches_at(sampleY * sampled.width + nearX) ||
                              matches_at(nearY * sampled.width + sampleX) ||
                              matches_at(nearY * sampled.width + nearX);
                }
                if (!matched) {
                    std::fprintf(stderr, "pixel_mismatch x=%u y=%u\n", x, y);
                    for (size_t c = 0; c < actual.size(); ++c)
                        std::fprintf(stderr, "channel=%zu expected=%g actual=%g expected_bits=%08x actual_bits=%08x\n",
                                     c, expected[c], actual[c], bits(expected[c]), bits(actual[c]));
                    throw PixelMismatch();
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
                   UINT firstResident, UINT sampledLevel, const char* capture,
                   ID3D12Resource* gpuConstants = nullptr)
{
    const auto& top = levels.front();
    draw_verified(device, path, levels, {top.width << firstResident, top.height << firstResident},
                  firstResident, {{sampledLevel, levels.at(sampledLevel).scale}}, capture, nullptr,
                  gpuConstants);
}

ComPtr<ID3D12Resource> produce_pixel_constants(ID3D12Device* device, const char* path)
{
    std::ifstream file(path, std::ios::binary);
    const std::vector<char> shader{std::istreambuf_iterator<char>(file), {}};
    if (shader.empty() || file.bad()) throw std::runtime_error("Cannot read compiled compute producer");

    D3D12_ROOT_PARAMETER parameter{};
    parameter.ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    parameter.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC signature{};
    signature.NumParameters = 1;
    signature.pParameters = &parameter;
    ComPtr<ID3DBlob> serialized;
    check(D3D12SerializeRootSignature(&signature, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, nullptr),
          "Serialize compute producer root");
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(),
                                      IID_PPV_ARGS(&root)), "Compute producer root");
    D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root.Get();
    desc.CS = {shader.data(), shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pipeline)), "Compute producer pipeline");

    auto constants = make_buffer(device, D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT,
                                 D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                 D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    ComputeCommands commands(device, pipeline.Get(), D3D12_COMMAND_LIST_TYPE_DIRECT);
    commands.list->SetComputeRootSignature(root.Get());
    commands.list->SetComputeRootUnorderedAccessView(0, constants->GetGPUVirtualAddress());
    commands.list->Dispatch(1, 1, 1);
    transition(commands.list.Get(), constants.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
               D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER);
    commands.submit_and_wait(device);
    return constants;
}
}

namespace {
UINT readWord(const char* data)
{
    UINT value;
    std::memcpy(&value, data, 4);
    return value;
}

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
    const auto next = [&](UINT magic) {
        UINT value = 0;
        if (size - at >= 4) std::memcpy(&value, data + at, 4);
        return size - at >= 4 && value == magic;
    };
    // Optional expected contents after the draw: magic 'X2WE', a slot count equal to the one above, then each slot
    // as a byte size equal to its initial size and its bytes.
    if (at != size && !next(0x49573258u)) {
        if (word("expected magic") != 0x45573258u) throw BadCase("Memory section has trailing bytes");
        if (word("expected slot count") != slotCount || !slotCount)
            throw BadCase("Expected memory names a different slot count");
        for (UINT i = 0; i < slotCount; ++i) {
            const UINT bytes = word("expected slot size");
            if (bytes != memory.slots[i].size()) throw BadCase("Expected memory slot size differs from its slot");
            if (size - at < bytes) throw BadCase("Expected memory is truncated in a slot");
            memory.expected.emplace_back(data + at, data + at + bytes);
            at += bytes;
        }
        if (at != size && !next(0x49573258u)) throw BadCase("Expected memory has trailing bytes");
    }
    // Optional storage images, last: magic 'X2WI', an image count (1 to 4) and a zero word, then each image as its slot
    // (0 to 3, ascending), channel count (1: R32_UINT, 4: R32G32B32A32_UINT), width and height (1 to 1024) and level
    // count (1 to 8, at most a full chain), then its initial texels and its expected texels after the draw, each as
    // every level in order with rows packed.
    if (at != size) {
        if (word("image magic") != 0x49573258u) throw BadCase("Memory section has trailing bytes");
        const UINT imageCount = word("image count");
        if (!imageCount || imageCount > 4) throw BadCase("Image section needs 1 to 4 images");
        if (word("image reserved") != 0) throw BadCase("Image section reserved word is not zero");
        for (UINT n = 0; n < imageCount; ++n) {
            StorageImage image{};
            image.slot = word("image slot");
            image.channels = word("image channels");
            image.width = word("image width");
            image.height = word("image height");
            image.levels = word("image levels");
            if (image.slot > 3 || (n && image.slot <= memory.images.back().slot))
                throw BadCase("Image slots are out of range or not ascending");
            if (image.channels != 1 && image.channels != 4) throw BadCase("Image channel count is not 1 or 4");
            if (!image.width || !image.height || image.width > 1024 || image.height > 1024)
                throw BadCase("Image extent is not 1 to 1024");
            if (!image.levels || image.levels > 8 || !((std::max)(image.width, image.height) >> (image.levels - 1)))
                throw BadCase("Image level count is not 1 to 8 or exceeds the full chain");
            UINT64 bytes = 0;
            for (UINT level = 0; level < image.levels; ++level) {
                const auto extent = Extent{image.width, image.height}.mip(level);
                bytes += UINT64(extent.width) * extent.height * 4 * image.channels;
            }
            if (size - at < 2 * bytes) throw BadCase("Image section is truncated in an image");
            image.initial.assign(data + at, data + at + bytes);
            image.expected.assign(data + at + bytes, data + at + 2 * bytes);
            at += static_cast<size_t>(2 * bytes);
            memory.images.push_back(std::move(image));
        }
        if (at != size) throw BadCase("Image section has trailing bytes");
    }
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

namespace {
// The 8x8 test texture: texel (x, y) holds (ramp[x], ramp[y], 128, 255), drawn one texel per 8x8 pixels.
PixelInput ramp_input(bool swapRB)
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
    return input;
}
}

static void check_pixel(ID3D12Device* device, const char* path, bool swapRB, const char* reference,
                        UINT8 writeMask, ID3D12Resource* gpuConstants)
{
    PixelInput input = ramp_input(swapRB);
    input.writeMask = writeMask;
    if (reference) {
        std::ifstream file(reference, std::ios::binary);
        const std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
        constexpr size_t fixed = 64 * sizeof(Word) + 64 * sizeof(Color);
        if (file.bad() || bytes.size() < fixed)
            throw BadCase("Expected a 256-byte constant buffer and 64 float4 reference colors");
        std::memcpy(input.constants.data(), bytes.data(), input.constants.size() * sizeof(Word));
        std::memcpy(input.expected.data(), bytes.data() + input.constants.size() * sizeof(Word),
                    input.expected.size() * sizeof(Color));
        size_t at = fixed;
        // Optional sections follow the fixed case, each led by its magic word: the 'X2WF' float-mode section
        // (from R0Y00/Xbox2Windows#363 by abilliontokens, as a magic-led section so it can precede the memory section)
        // and then the memory section, which runs to the end of the file.
        if (bytes.size() - at >= 4 && readWord(bytes.data() + at) == 0x46573258u) {
            constexpr size_t section = 4 + 4 + 64;
            if (bytes.size() - at < section) throw BadCase("Float-mode section is truncated");
            const UINT flags = readWord(bytes.data() + at + 4);
            if (flags & ~1u) throw BadCase("Unknown float-mode section flag bits");
            input.integerRT = (flags & 1u) != 0;
            input.nanMask.assign(bytes.data() + at + 8, bytes.data() + at + section);
            for (BYTE mask : input.nanMask)
                if (mask & 0xf0u) throw BadCase("NaN-class mask names a channel beyond the fourth");
            at += section;
        }
        if (bytes.size() > at && static_cast<BYTE>(bytes[at]) <= 3u) {
            // Upstream's case trailer (R0Y00/Xbox2Windows#363 and #552), told apart from the magic-led sections by its
            // first byte: a flags byte (bit 0: integer target, bit 1: a viewport rectangle of four words follows),
            // then optionally 64 NaN-class mask bytes, to the end of the file.
            const UINT flags = static_cast<BYTE>(bytes[at++]);
            input.integerRT = (flags & 1u) != 0;
            if (flags & 2u) {
                std::array<UINT, 4> rect{};
                if (bytes.size() - at < sizeof(rect)) throw BadCase("Invalid pixel case viewport");
                std::memcpy(rect.data(), bytes.data() + at, sizeof(rect));
                at += sizeof(rect);
                const auto [left, top, width, height] = rect;
                if (!width || !height || left >= input.width || top >= input.height ||
                    width > input.width - left || height > input.height - top)
                    throw BadCase("Invalid pixel case viewport");
                // Explicit viewport cases provide one reference color per target pixel.
                input.scale = 1;
                input.viewport = D3D12_VIEWPORT{float(left), float(top), float(width), float(height), 0, 1};
            }
            if (bytes.size() > at) {
                if (input.integerRT) throw BadCase("NaN-class masks require a floating-point render target");
                if (bytes.size() - at != 64) throw BadCase("Expected exactly 64 NaN mask bytes after the case trailer fields");
                input.nanMask.assign(bytes.data() + at, bytes.data() + bytes.size());
                at = bytes.size();
            }
        }
        if (bytes.size() > at) input.memory = parse_memory_section(bytes.data() + at, bytes.size() - at);
    }
    std::vector<PixelInput> levels;
    levels.push_back(std::move(input));
    draw_verified(device, path, levels, 0, 0, nullptr, gpuConstants);
}

void check_translated_pixel(ID3D12Device* device, const char* path, bool swapRB, const char* reference, UINT8 writeMask)
{
    check_pixel(device, path, swapRB, reference, writeMask, nullptr);
}

void check_compute_to_pixel(ID3D12Device* device, const char* compute, const char* pixel,
                            const char* reference, const char* previous)
{
    auto stale = previous ? produce_pixel_constants(device, previous) : ComPtr<ID3D12Resource>{};
    auto current = produce_pixel_constants(device, compute);
    check_pixel(device, pixel, false, reference, D3D12_COLOR_WRITE_ENABLE_ALL,
                stale ? stale.Get() : current.Get());
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

// The outputs case: 256 bytes of constants, then magic 'X2WO', the target count N (0..8), a depth flag (0 or 1) and a
// zero word, N write masks (one word each, 0..15), N x 64 float4 references (target by target, texel by texel in
// row-major order), and with the depth flag 64 binary32 depth references. N = 0 binds no render target, so a pixel
// shader without outputs is drawn into the depth target alone; a case with neither is refused.
void check_pixel_outputs(ID3D12Device* device, const char* path, const char* reference)
{
    PixelInput input = ramp_input(false);
    std::ifstream file(reference, std::ios::binary);
    const std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
    constexpr size_t header = 64 * sizeof(Word) + 4 * sizeof(UINT);
    if (file.bad() || bytes.size() < header) throw BadCase("Expected 256 bytes of constants and an outputs header");
    std::memcpy(input.constants.data(), bytes.data(), input.constants.size() * sizeof(Word));
    std::array<UINT, 4> head;
    std::memcpy(head.data(), bytes.data() + 64 * sizeof(Word), sizeof(head));
    const auto [magic, count, depth, reserved] = head;
    if (magic != 0x4f573258u || count > 8 || depth > 1 || reserved || (!count && !depth))
        throw BadCase("Outputs header needs magic X2WO, at most 8 targets, a depth flag of 0 or 1 and a zero word");
    const size_t texels = input.expected.size();
    if (bytes.size() != header + count * (sizeof(UINT) + texels * sizeof(Color)) + depth * texels * sizeof(float))
        throw BadCase("Outputs case size does not match its header");
    PixelOutputs outputs;
    outputs.masks.resize(count);
    std::memcpy(outputs.masks.data(), bytes.data() + header, count * sizeof(UINT));
    if (std::any_of(outputs.masks.begin(), outputs.masks.end(), [](UINT mask) { return mask > 15; }))
        throw BadCase("A target write mask is not 0..15");
    const char* at = bytes.data() + header + count * sizeof(UINT);
    for (UINT t = 0; t < count; ++t, at += texels * sizeof(Color)) {
        outputs.expected.emplace_back(texels);
        std::memcpy(outputs.expected.back().data(), at, texels * sizeof(Color));
    }
    outputs.depth = depth != 0;
    if (outputs.depth) {
        outputs.expectedDepth.resize(texels);
        std::memcpy(outputs.expectedDepth.data(), at, texels * sizeof(float));
    }
    std::vector<PixelInput> levels;
    levels.push_back(std::move(input));
    draw_verified(device, path, levels, {8, 8}, 0, {{0, levels.front().scale}}, nullptr, &outputs);
}

void check_attribute_pixel(ID3D12Device* device, const char* shader, const char* reference, bool rg)
{
    PixelInput input{32, 32, 1, DXGI_FORMAT_R8G8B8A8_UNORM};
    if (rg) input.writeMask = D3D12_COLOR_WRITE_ENABLE_RED | D3D12_COLOR_WRITE_ENABLE_GREEN;
    input.rows.resize(input.width * input.height * 4);
    input.expected.resize(input.width * input.height);
    std::ifstream file(reference, std::ios::binary);
    file.read(reinterpret_cast<char*>(input.constants.data()), input.constants.size() * sizeof(Word));
    file.read(reinterpret_cast<char*>(input.expected.data()), input.expected.size() * sizeof(Color));
    if (!file || file.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("Expected a 256-byte constant buffer and 32 by 32 float4 colors");
    draw_verified(device, shader, {std::move(input)}, 0, 0, nullptr);
}

void check_sampled_coverage(ID3D12Device* device, const char* shader, const char* reference)
{
    PixelInput input{8, 8, 1, DXGI_FORMAT_R8G8B8A8_UNORM};
    for (UINT y = 0; y < 8; ++y) {
        for (UINT x = 0; x < 8; ++x) {
            BYTE alpha = BYTE((x*41 + y*19) & 255);
            input.rows.insert(input.rows.end(), {255, 0, 128, alpha});
            input.secondRows.insert(input.secondRows.end(), {0, 255, 128, BYTE(255-alpha)});
        }
    }
    input.expected.assign(64, Color{-1, -1, -1, -1});
    input.coverage.resize(64);
    std::ifstream file(reference, std::ios::binary);
    file.read(reinterpret_cast<char*>(input.constants.data()), input.constants.size() * sizeof(Word));
    file.read(reinterpret_cast<char*>(input.coverage.data()), input.coverage.size());
    if (!file || file.peek() != std::char_traits<char>::eof() ||
        std::any_of(input.coverage.begin(), input.coverage.end(), [](BYTE v){ return v > 1; }))
        throw std::runtime_error("Invalid coverage case");
    draw_verified(device, shader, {input}, 0, 0, nullptr);
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
