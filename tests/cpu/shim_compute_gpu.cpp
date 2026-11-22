// Dispatch the repository's source-built compute fixture from the host provider.
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <array>
#include <cstdio>
#include <cstring>

#include "pso_compute_embedded.h"

namespace {
using Microsoft::WRL::ComPtr;

void require(HRESULT hr, const char* operation)
{
    if (FAILED(hr)) {
        std::fprintf(stderr, "%s failed (HRESULT 0x%08lx)\n", operation, static_cast<unsigned long>(hr));
        throw hr;
    }
}

ComPtr<ID3D12Device> create_device()
{
    ComPtr<IDXGIFactory6> factory;
    require(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2");
    ComPtr<IDXGIAdapter1> adapter;
    char backend[16]{};
    const auto size = GetEnvironmentVariableA("X2W_SHIM_COMPUTE_ADAPTER", backend, sizeof(backend));
    if (!size || (size < sizeof(backend) && std::strcmp(backend, "warp") == 0)) {
        require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
    } else if (size < sizeof(backend) && std::strcmp(backend, "hardware") == 0) {
        for (UINT i = 0;; ++i) {
            const HRESULT hr = factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                                   IID_PPV_ARGS(&adapter));
            if (hr == DXGI_ERROR_NOT_FOUND) {
                std::fputs("no D3D12 physical adapter\n", stderr);
                ExitProcess(77);
            }
            require(hr, "EnumAdapterByGpuPreference");
            DXGI_ADAPTER_DESC1 desc{};
            require(adapter->GetDesc1(&desc), "GetDesc1");
            if (!(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) {
                const HRESULT support = D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0,
                                                          __uuidof(ID3D12Device), nullptr);
                if (support != DXGI_ERROR_UNSUPPORTED) {
                    require(support, "Probe physical device");
                    break;
                }
            }
            adapter.Reset();
        }
    } else {
        require(E_INVALIDARG, "Select compute adapter");
    }
    ComPtr<ID3D12Device> device;
    require(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice");
    return device;
}

ComPtr<ID3D12Resource> make_buffer(ID3D12Device* device, UINT64 bytes, D3D12_HEAP_TYPE type,
                                   D3D12_RESOURCE_STATES state, D3D12_RESOURCE_FLAGS flags)
{
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = type;
    heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = flags;
    ComPtr<ID3D12Resource> buffer;
    require(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
                                            IID_PPV_ARGS(&buffer)), "CreateCommittedResource");
    return buffer;
}
}

bool shim_compute_gpu(unsigned seed, unsigned* output, unsigned words)
{
    constexpr std::array<unsigned, 4> input{1, 2, 3, 4};
    if (!output || words != input.size()) return false;
    try {
        auto device = create_device();
        ComPtr<ID3D12RootSignature> root;
        require(device->CreateRootSignature(0, pso_compute_embedded, sizeof(pso_compute_embedded),
                                            IID_PPV_ARGS(&root)), "CreateRootSignature");
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
        desc.pRootSignature = root.Get();
        desc.CS = {pso_compute_embedded, sizeof(pso_compute_embedded)};
        ComPtr<ID3D12PipelineState> pipeline;
        require(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pipeline)), "CreateComputePipelineState");

        auto upload = make_buffer(device.Get(), sizeof(input), D3D12_HEAP_TYPE_UPLOAD,
                                  D3D12_RESOURCE_STATE_GENERIC_READ, D3D12_RESOURCE_FLAG_NONE);
        auto result = make_buffer(device.Get(), sizeof(input), D3D12_HEAP_TYPE_DEFAULT,
                                  D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        auto readback = make_buffer(device.Get(), sizeof(input), D3D12_HEAP_TYPE_READBACK,
                                    D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE);
        const D3D12_RANGE empty{};
        const D3D12_RANGE range{0, sizeof(input)};
        void* data = nullptr;
        require(upload->Map(0, &empty, &data), "Map upload");
        std::memcpy(data, input.data(), sizeof(input));
        upload->Unmap(0, &range);

        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
        ComPtr<ID3D12CommandQueue> queue;
        require(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
        ComPtr<ID3D12CommandAllocator> allocator;
        require(device->CreateCommandAllocator(queue_desc.Type, IID_PPV_ARGS(&allocator)), "CreateCommandAllocator");
        ComPtr<ID3D12GraphicsCommandList> list;
        require(device->CreateCommandList(0, queue_desc.Type, allocator.Get(), pipeline.Get(), IID_PPV_ARGS(&list)),
                "CreateCommandList");
        std::array<unsigned, 16> constants{words, 7};
        constants[13] = seed;
        list->SetComputeRootSignature(root.Get());
        list->SetComputeRootShaderResourceView(0, upload->GetGPUVirtualAddress());
        list->SetComputeRootUnorderedAccessView(1, result->GetGPUVirtualAddress());
        list->SetComputeRoot32BitConstants(2, static_cast<UINT>(constants.size()), constants.data(), 0);
        list->Dispatch(1, 1, 1);
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {result.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                              D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE};
        list->ResourceBarrier(1, &barrier);
        list->CopyBufferRegion(readback.Get(), 0, result.Get(), 0, sizeof(input));
        require(list->Close(), "Close compute commands");
        ComPtr<ID3D12Fence> fence;
        require(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
        ID3D12CommandList* commands[]{list.Get()};
        queue->ExecuteCommandLists(1, commands);
        require(queue->Signal(fence.Get(), 1), "Signal compute fence");
        require(fence->SetEventOnCompletion(1, nullptr), "Wait for compute fence");
        require(device->GetDeviceRemovedReason(), "Compute completion");

        require(readback->Map(0, &range, &data), "Map readback");
        std::memcpy(output, data, sizeof(input));
        readback->Unmap(0, &empty);
        return true;
    } catch (HRESULT) {
        return false;
    }
}
