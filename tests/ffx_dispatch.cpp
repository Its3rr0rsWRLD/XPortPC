#define NOMINMAX
#include "ffx_provider_loop.h"
#include "ffx_dispatch_scratch.h"
#include "bvh_fixture.h"
#include "producerNative.h"
#include "producerPacked.h"
#include "rcasNative.h"
#include "rcasPacked.h"
#include <algorithm>
#include <cmath>

#ifndef FFX_PACKAGE_DEVICE_SLICE
DispatchGrid producer_grid(uint32_t width, uint32_t height) { return {(width+31)/32,(height+31)/32,1}; }
DispatchGrid rcas_grid(uint32_t width, uint32_t height) { return {(width+15)/16,(height+15)/16,1}; }

void dispatch_aliases(RecurrentProvider& provider, bool sharpen)
{
    const auto output = provider.mirror[12];
    provider.mirror[10] = sharpen ? provider.resources[16] : output;
    provider.mirror[11] = provider.resources[24] = output;
    if (sharpen)
        provider.resources[11] = output;
}
#endif

namespace {
using RGB = std::array<float,3>;
constexpr float log_scale = 12.2887f;

uint32_t record_field(const void* records, uint32_t index)
{
    uint32_t slot;
    std::memcpy(&slot, static_cast<const uint8_t*>(records) + 64*index + 0x34, sizeof slot);
    return slot;
}

D3D12_TEXTURE_COPY_LOCATION texture_location(ID3D12Resource* object)
{
    D3D12_TEXTURE_COPY_LOCATION where{};
    where.pResource = object;
    where.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    return where;
}

D3D12_TEXTURE_COPY_LOCATION footprint(ID3D12Resource* buffer, DXGI_FORMAT format,
                                      UINT width, UINT height, UINT64 offset = 0)
{
    D3D12_TEXTURE_COPY_LOCATION where{};
    where.pResource = buffer;
    where.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    where.PlacedFootprint = {offset, {format, width, height, 1, 256}};
    return where;
}

// An exactly representable quadrant pattern exposes transposed coordinates and
// missing 8x8 quadrants in the four-store RCAS group. Overwrite the first 8x4.
uint32_t guard_word(UINT x, UINT y)
{
    const unsigned q = (x >= 8) + 2*(y >= 8);
    return (14u<<27) | (48u + 32*q) | ((160u - 24*q)<<9) | ((80u + 16*q)<<18);
}

RGB decoded(uint32_t word)
{
    RGB rgb;
    for (UINT c=0; c<3; ++c)
        rgb[c] = std::ldexp(float((word>>(9*c))&511), int(word>>27)-24);
    return rgb;
}

#ifdef FFX_DISPATCH_AOT
// Independent FP32 reference for the package's half-precision five-tap stage.
// The fixture has unit exposure, pre-exposure and a sharpening coefficient of 0.5.
RGB sharpen(const std::vector<uint32_t>& words, int x, int y, const RGB& center)
{
    auto tap = [&](int px, int py) -> RGB {
        if (px<0 || py<0) return {};
        return decoded(words[64*py+px]);
    };
    const RGB ring[] = {tap(x,y-1),tap(x-1,y),tap(x+1,y),tap(x,y+1)};
    auto luma = [](const RGB& v) { return v[1] + 0.5f*(v[0]+v[2]); };
    const float middle = luma(center);
    float low = luma(ring[0]), high = low, sum_luma = 0;
    for (auto& pixel : ring) {
        low = std::min(low,luma(pixel));
        high = std::max(high,luma(pixel));
        sum_luma += luma(pixel);
    }
    float range = std::max(high,middle)-std::min(low,middle);
    float noise = range ? std::clamp(std::abs(0.25f*sum_luma-middle)/range,0.f,1.f) : 0;
    float dark = low ? std::min(1.f,middle/low) : 1.f;
    float lobe = -0.1875f;
    RGB sum{};
    for (int c=0; c<3; ++c) {
        float lo = ring[0][c], hi = lo;
        for (auto& pixel : ring) {
            lo = std::min(lo,pixel[c]);
            hi = std::max(hi,pixel[c]);
            sum[c] += pixel[c];
        }
        lobe = std::max({lobe, -dark*lo/(4*hi), (1-hi)/(4*lo-4)});
    }
    lobe = std::min(0.f,lobe)*0.5f*(1-0.5f*noise);
    RGB result{};
    for (int c=0; c<3; ++c)
        result[c] = (center[c]+lobe*sum[c])/(1+4*lobe);
    return result;
}
#endif
}

static std::vector<uint32_t> run_dispatch(LoopContext& ctx, const void* records, ScratchInput input)
{
    auto* device = ctx.probe.device;
    if (producer_grid(1920,1080) != DispatchGrid{60,34,1} ||
        rcas_grid(1920,1080) != DispatchGrid{120,68,1} ||
        producer_grid(33,17) != DispatchGrid{2,1,1} || rcas_grid(33,17) != DispatchGrid{3,2,1})
        throw std::runtime_error("Dispatch dimension lowering mismatch");
    auto provider = ctx.state;
    // External dispatch output gets its own handle, distinct from all context resources.
    const UINT external = UINT(ctx.objects.size());
    provider.mirror[12] = external;
    dispatch_aliases(provider, false);
    if (provider.mirror[10] != external || provider.mirror[11] != external ||
        provider.resources[24] != external || provider.resources[11] != ctx.state.resources[11])
        throw std::runtime_error("Disabled sharpening alias mismatch");
    dispatch_aliases(provider, true);
    const auto index = provider.mirror[10];
    if (index != provider.resources[16] || provider.mirror[11] != external ||
        provider.resources[11] != external || provider.resources[24] != external)
        throw std::runtime_error("Enabled sharpening alias mismatch");
    auto* intermediate = ctx.objects.at(index).Get();
    auto desc = intermediate->GetDesc();
    const auto format = desc.Format;
    const bool packed = format == DXGI_FORMAT_R32_UINT;
    desc.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    desc.Width = desc.Height = 16;
    auto output = resource(device, desc, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);

    constexpr auto type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    D3D12_DESCRIPTOR_HEAP_DESC hd{type, 5, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap;
    check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)), "Create dispatch heap");
    const auto stride = device->GetDescriptorHandleIncrementSize(type);
    auto handle = [stride](ID3D12DescriptorHeap* h, UINT offset) {
        auto base = h->GetCPUDescriptorHandleForHeapStart();
        base.ptr += offset * stride;
        return base;
    };
    UINT slot = 0;
    for (UINT id : {10u,14u,13u}) {
        auto from = handle(ctx.probe.heaps[1].Get(), record_field(records, provider.mirror.at(id)));
        device->CopyDescriptorsSimple(1, handle(heap.Get(), slot++), from, type);
    }
    device->CopyDescriptorsSimple(1, handle(heap.Get(), 3),
                                  handle(ctx.probe.heaps[0].Get(), provider.resources[16]), type);
    device->CreateUnorderedAccessView(output.Get(), nullptr, nullptr, handle(heap.Get(), 4));
    const RGB log_color{0.125f,0.25f,0.375f};
    RGB linear;
    for (UINT c=0; c<3; ++c)
        linear[c] = (std::exp2(log_scale * log_color[c]*0.5f)-1)/150;
    auto scene = bvh_fixture::upload(device, std::vector<RGB>(32, linear));
    auto history = bvh_fixture::upload(device, std::vector<RGB>(32, log_color));

    // Initialize the one-texel sampling halo and poison all 256 final pixels.
    constexpr UINT final_offset = 4608;
    std::vector<uint32_t> seed((final_offset+4096)/4, 0x7fc00000);
    for (UINT y=0; y<17; ++y)
        for (UINT x=0; x<17; ++x)
            seed[64*y+x] = guard_word(x,y);
    auto init = bvh_fixture::upload(device, seed);
    auto back = make_buffer(device, seed.size()*4, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    const D3D12_SHADER_BYTECODE p = packed ? D3D12_SHADER_BYTECODE{producerPacked,sizeof(producerPacked)}
                                          : D3D12_SHADER_BYTECODE{producerNative,sizeof(producerNative)};
    const D3D12_SHADER_BYTECODE r = packed ? D3D12_SHADER_BYTECODE{rcasPacked,sizeof(rcasPacked)}
                                          : D3D12_SHADER_BYTECODE{rcasNative,sizeof(rcasNative)};
    bvh_fixture::Kernel writer(device,p), reader(device,r);
    DispatchScratch scratch(device,ctx.objects.at(provider.resources.at(22)).Get(),input);
    ComputeCommands cmd(device, writer.pipeline.Get(), D3D12_COMMAND_LIST_TYPE_DIRECT);
    auto* list = cmd.list.Get();
    auto tex = texture_location(intermediate), out = texture_location(output.Get());
    auto src = footprint(init.Get(), format, 17,17);
    auto dst = footprint(init.Get(), desc.Format, 16,16,final_offset);
    constexpr auto uav = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    constexpr auto sample = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    transition(list,intermediate,uav,D3D12_RESOURCE_STATE_COPY_DEST);
    list->CopyTextureRegion(&tex,0,0,0,&src,nullptr);
    list->CopyTextureRegion(&out,0,0,0,&dst,nullptr);
    transition(list,intermediate,D3D12_RESOURCE_STATE_COPY_DEST,uav);
    transition(list,output.Get(),D3D12_RESOURCE_STATE_COPY_DEST,uav);
    auto* visible = heap.Get();
    list->SetDescriptorHeaps(1,&visible);
    auto gpu = heap->GetGPUDescriptorHandleForHeapStart();
    scratch.produce(list);
    list->SetPipelineState(writer.pipeline.Get());
    list->SetComputeRootSignature(writer.root.Get());
    list->SetComputeRootDescriptorTable(0,gpu);
    list->SetComputeRootShaderResourceView(1,scene->GetGPUVirtualAddress());
    list->SetComputeRootShaderResourceView(2,history->GetGPUVirtualAddress());
    scratch.bind_consumer(list);
    auto groups = producer_grid(8,4);
    list->Dispatch(groups[0],groups[1],groups[2]);
    scratch.finish(list);
    transition(list,intermediate,uav,sample);
    list->SetPipelineState(reader.pipeline.Get());
    list->SetComputeRootSignature(reader.root.Get());
    gpu.ptr += 3 * stride;
    list->SetComputeRootDescriptorTable(0,gpu);
    groups = rcas_grid(8,4);
    list->Dispatch(groups[0],groups[1],groups[2]);
    transition(list,intermediate,sample,D3D12_RESOURCE_STATE_COPY_SOURCE);
    transition(list,output.Get(),uav,D3D12_RESOURCE_STATE_COPY_SOURCE);
    src.pResource = dst.pResource = back.Get();
    const D3D12_BOX tile{0,0,0,17,17,1};
    list->CopyTextureRegion(&src,0,0,0,&tex,&tile);
    list->CopyTextureRegion(&dst,0,0,0,&out,nullptr);
    transition(list,intermediate,D3D12_RESOURCE_STATE_COPY_SOURCE,uav);
    cmd.submit_and_wait(device);
    scratch.verify();
    const auto words = bvh_fixture::read(back.Get(),seed.size());
    for (UINT y=0; y<17; ++y)
        for (UINT x=0; x<17; ++x) {
            const bool active = x<8 && y<4;
            const auto raw = words[y*64+x];
            const auto color = decoded(raw);
            if (active) {
                const float history_weight=scratch.expected_history_fraction(x,y);
                const float gain=0.5f+0.5f*history_weight;
                int exponent;
                static_cast<void>(std::frexp(log_color[2]*gain,&exponent));
                const float unit=std::ldexp(1.f,exponent-9);
                for (UINT c=0; c<3; ++c) {
                    const float expected=log_color[c]*gain;
                    if (std::abs(color[c]-expected)>0.501f*unit+0.000001f) {
                        std::fprintf(stderr,"scratch mode=%u pixel=(%u,%u) channel=%u got=%g expected=%g\n",
                                     unsigned(input),x,y,c,color[c],expected);
                        throw std::runtime_error("Pass 26 blend mismatch");
                    }
                }
            } else if (raw!=guard_word(x,y)) {
                throw std::runtime_error("Pass 26 guard texel mismatch");
            }
            if (x>=16 || y>=16) continue;
#ifdef FFX_DISPATCH_AOT
            const auto filtered = sharpen(words,x,y,color);
#else
            const auto filtered = color;
#endif
            float pixel[4];
            std::memcpy(pixel, &words[final_offset/4+64*y+4*x], sizeof pixel);
            for (UINT c=0; c<3; ++c) {
                const float oracle = std::max(0.f,(std::exp2(log_scale * filtered[c])-1)/150);
                if (!std::isfinite(pixel[c]) || pixel[c]<0 ||
                    std::abs(pixel[c]-oracle) > oracle*0.025f+0.00005f) {
                    std::fprintf(stderr,"RCAS pixel=(%u,%u) channel=%u got=%g expected=%g\n",x,y,c,pixel[c],oracle);
                    throw std::runtime_error("RCAS dispatch readback mismatch");
                }
            }
            if (pixel[0] != pixel[3]) throw std::runtime_error("RCAS alpha store mismatch");
        }
#ifdef FFX_DISPATCH_AOT
    const char* source = "package-aot";
#else
    const char* source = "desktop-control";
#endif
    const char* mode = input==ScratchInput::bypass ? "bypass" : (input==ScratchInput::zero ? "zero" : "pattern");
    std::printf("dispatch=%s pass=26 u2_index=%u rcas_t18_index=%u format=%u tile=8x4 scratch=%s reads=72 final_pixels=256 mismatches=0\n",
                source,index,provider.resources[16],unsigned(format),mode);
    return words;
}

void check_ffx_dispatch(LoopContext& ctx, const void* records)
{
    run_dispatch(ctx,records,ScratchInput::bypass);
    auto zero=run_dispatch(ctx,records,ScratchInput::zero);
    auto pattern=run_dispatch(ctx,records,ScratchInput::pattern);
    unsigned intermediate_changes=0, final_changes=0;
    for (unsigned y=0; y<4; ++y)
        for (unsigned x=0; x<8; ++x) {
            intermediate_changes += zero[y*64+x]!=pattern[y*64+x];
            const unsigned offset=4608/4+64*y+4*x;
            final_changes += std::memcmp(&zero[offset],&pattern[offset],16)!=0;
        }
    if (!intermediate_changes || !final_changes)
        throw std::runtime_error("Upstream input did not reach both downstream stages");
    std::printf("scratch_zero_vs_pattern intermediate_changed=%u final_active_changed=%u\n",
                intermediate_changes,final_changes);
}
