#include "desktop_gpu.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;

namespace {
std::vector<char> read_bytes(const char* path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("Cannot open draw input");
    return {std::istreambuf_iterator<char>(stream), {}};
}

}

void check_depth_mask_draw(ID3D12Device* device, const char* first, const char* second, const char* fixture, bool swap)
{
    constexpr UINT side = 32;
    constexpr UINT cb_bytes = 2048;
    const auto input = read_bytes(fixture);
    if (input.size() != 2 * cb_bytes + side * side * 4)
        throw std::runtime_error("Invalid draw fixture size");
    auto shader = read_bytes(first);
    auto pixel = read_bytes(second);
    D3D12_ROOT_PARAMETER params[2]{};
    for (UINT i = 0; i < 2; ++i) {
        params[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
        params[i].Descriptor.ShaderRegister = i;
    }
    D3D12_ROOT_SIGNATURE_DESC layout{};
    layout.NumParameters = 2;
    layout.pParameters = params;
    ComPtr<ID3DBlob> blob;
    check(D3D12SerializeRootSignature(&layout, D3D_ROOT_SIGNATURE_VERSION_1, &blob, nullptr), "Serialize draw root");
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)), "Draw root");
    ComPtr<ID3D12PipelineState> pipeline;
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root.Get();
    desc.VS = {shader.data(), shader.size()};
    desc.PS = {pixel.data(), pixel.size()};
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.DepthStencilState.DepthEnable = TRUE;
    desc.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ALL;
    desc.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    desc.DSVFormat = DXGI_FORMAT_D32_FLOAT;
    desc.SampleMask = UINT_MAX;
    desc.SampleDesc.Count = 1;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    check(device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pipeline)), "Create depth-only pipeline");
    D3D12_RESOURCE_DESC texture{};
    texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    texture.Width = texture.Height = side;
    texture.DepthOrArraySize = texture.MipLevels = texture.SampleDesc.Count = 1;
    texture.Format = DXGI_FORMAT_D32_FLOAT;
    texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
    constexpr auto draw_state = D3D12_RESOURCE_STATE_DEPTH_WRITE;
    D3D12_CLEAR_VALUE clear_value{};
    clear_value.Format = texture.Format;
    clear_value.DepthStencil.Depth = 0.9375f;
    auto target = resource(device, texture, D3D12_HEAP_TYPE_DEFAULT, draw_state, &clear_value);
    D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
    heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
    heap_desc.NumDescriptors = 1;
    ComPtr<ID3D12DescriptorHeap> heap;
    check(device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&heap)), "Create target heap");
    auto handle = heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateDepthStencilView(target.Get(), nullptr, handle);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 size = 0;
    device->GetCopyableFootprints(&texture, 0, 1, 0, &footprint, nullptr, nullptr, &size);
    auto readback = make_buffer(device, size, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    auto upload = make_buffer(device, 2 * cb_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped = nullptr;
    D3D12_RANGE empty{};
    check(upload->Map(0, &empty, &mapped), "Map draw input");
    std::memcpy(mapped, input.data(), 2 * cb_bytes);
    upload->Unmap(0, nullptr);
    ComputeCommands commands(device, pipeline.Get(), D3D12_COMMAND_LIST_TYPE_DIRECT);
    auto* list = commands.list.Get();
    list->SetGraphicsRootSignature(root.Get());
    const auto base = upload->GetGPUVirtualAddress();
    list->SetGraphicsRootConstantBufferView(0, base + (swap ? cb_bytes : 0));
    list->SetGraphicsRootConstantBufferView(1, base + (swap ? 0 : cb_bytes));
    const D3D12_VIEWPORT viewport{0, 0, side, side, 0, 1};
    const D3D12_RECT scissor{0, 0, side, side};
    list->RSSetViewports(1, &viewport);
    list->RSSetScissorRects(1, &scissor);
    list->OMSetRenderTargets(0, nullptr, FALSE, &handle);
    list->ClearDepthStencilView(handle, D3D12_CLEAR_FLAG_DEPTH, 0.9375f, 0, 0, nullptr);
    list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    list->DrawInstanced(3, 1, 0, 0);
    transition(list, target.Get(), draw_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION src{}, dst{};
    src.pResource = target.Get();
    dst.pResource = readback.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = footprint;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    commands.submit_and_wait(device);
    check(readback->Map(0, nullptr, &mapped), "Map draw result");
    const char* rows = static_cast<const char*>(mapped);
    const char* reference = input.data() + 2 * cb_bytes;
    unsigned mismatches = 0;
    for (UINT y = 0; y < side; ++y)
        for (UINT x = 0; x < side; ++x)
            mismatches += std::memcmp(rows + footprint.Offset + y * footprint.Footprint.RowPitch + 4*x,
                                      reference + (y * side + x) * 4, 4) != 0;
    readback->Unmap(0, &empty);
    std::printf("pixels=1024 mismatches=%u\n", mismatches);
    if (mismatches) throw std::runtime_error("Draw reference mismatch");
}
