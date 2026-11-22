#include "../desktop_gpu.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {
struct WindowCase {
    const char* name;
    std::array<UINT, 4> parameters;  // first base, second address, destination address, first base high
    UINT expected;
};

constexpr UINT left = 0xfedcba98u;
constexpr UINT right = 0x12345678u;
constexpr WindowCase cases[] = {
    {"baseline", {8, 28, 44, 0}, left - right},
    {"swapped", {24, 12, 44, 0}, right - left},
    {"moved output", {8, 28, 52, 0}, left - right},
    {"high address", {8, 28, 44, 1}, 0u - right},
    {"unaligned", {9, 28, 44, 0}, 0u - right},
    {"index addition wraps", {0xfffffffcu, 28, 44, 0xffffffffu}, 0u - right},
    {"unaligned write", {8, 28, 45, 0}, 0},
    {"write beyond descriptor", {8, 28, 64, 0}, 0},
};
}

void check_spirv_window(ID3D12Device* device, const char* shader_path)
{
    std::ifstream shader(shader_path, std::ios::binary);
    if (!shader) throw std::runtime_error("Cannot open address-window shader");
    const std::vector<char> bytes(std::istreambuf_iterator<char>(shader), {});
    D3D12_DESCRIPTOR_RANGE ranges[] = {{D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 1, 0, 1, 0},
                                       {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 0, 2, 0}};
    D3D12_ROOT_PARAMETER parameters[2]{};
    for (UINT i = 0; i < 2; ++i) {
        parameters[i].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[i].DescriptorTable = {1, &ranges[i]};
    }
    D3D12_ROOT_SIGNATURE_DESC root_desc{2, parameters};
    ComPtr<ID3DBlob> root_bytes, error;
    check(D3D12SerializeRootSignature(&root_desc, D3D_ROOT_SIGNATURE_VERSION_1, &root_bytes, &error),
          "Serialize address-window root signature");
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0, root_bytes->GetBufferPointer(), root_bytes->GetBufferSize(),
                                      IID_PPV_ARGS(&root)), "Create address-window root signature");
    D3D12_COMPUTE_PIPELINE_STATE_DESC pso{};
    pso.pRootSignature = root.Get();
    pso.CS = {bytes.data(), bytes.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check(device->CreateComputePipelineState(&pso, IID_PPV_ARGS(&pipeline)), "Create address-window pipeline");

    for (const auto& test : cases) {
        std::array<UINT, 16> expected;
        expected.fill(0xcba98765u);
        expected[3] = left;
        expected[7] = right;
        auto upload = make_buffer(device, 128, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
        auto arena = make_buffer(device, sizeof(expected), D3D12_HEAP_TYPE_DEFAULT,
                                 D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        auto readback = make_buffer(device, sizeof(expected), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_RANGE empty{};
        void* mapped = nullptr;
        check(upload->Map(0, &empty, &mapped), "Map address-window upload");
        std::memcpy(mapped, test.parameters.data(), sizeof(test.parameters));
        std::memcpy(static_cast<BYTE*>(mapped) + 64, expected.data(), sizeof(expected));
        upload->Unmap(0, nullptr);
        const UINT destination = test.parameters[2];
        if (destination % 4 == 0 && destination < sizeof(expected)) expected[destination / 4] = test.expected;

        D3D12_DESCRIPTOR_HEAP_DESC desc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 2,
                                        D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE};
        ComPtr<ID3D12DescriptorHeap> heap;
        check(device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&heap)), "Create address-window descriptors");
        auto cpu = heap->GetCPUDescriptorHandleForHeapStart();
        UINT stride = device->GetDescriptorHandleIncrementSize(desc.Type);
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_R32_TYPELESS;
        srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Buffer.NumElements = static_cast<UINT>(test.parameters.size());
        srv.Buffer.Flags = D3D12_BUFFER_SRV_FLAG_RAW;
        device->CreateShaderResourceView(upload.Get(), &srv, cpu);
        cpu.ptr += stride;
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = DXGI_FORMAT_R32_TYPELESS;
        uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        uav.Buffer.NumElements = static_cast<UINT>(expected.size());
        uav.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
        device->CreateUnorderedAccessView(arena.Get(), nullptr, &uav, cpu);

        ComputeCommands commands(device, pipeline.Get());
        auto& list = commands.list;
        transition(list.Get(), arena.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
        list->CopyBufferRegion(arena.Get(), 0, upload.Get(), 64, sizeof(expected));
        transition(list.Get(), arena.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[] = {heap.Get()};
        list->SetDescriptorHeaps(1, heaps);
        auto gpu = heap->GetGPUDescriptorHandleForHeapStart();
        list->SetComputeRootDescriptorTable(0, gpu);
        gpu.ptr += stride;
        list->SetComputeRootDescriptorTable(1, gpu);
        list->Dispatch(1, 1, 1);
        transition(list.Get(), arena.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE);
        list->CopyBufferRegion(readback.Get(), 0, arena.Get(), 0, sizeof(expected));
        commands.submit_and_wait(device);
        D3D12_RANGE read{0, sizeof(expected)};
        check(readback->Map(0, &read, &mapped), "Map address-window readback");
        std::array<UINT, 16> actual;
        std::memcpy(actual.data(), mapped, sizeof(actual));
        readback->Unmap(0, &empty);
        for (size_t i = 0; i < expected.size(); ++i) {
            if (actual[i] != expected[i]) {
                std::fprintf(stderr, "%s word %zu expected %08x observed %08x\n", test.name, i, expected[i], actual[i]);
                throw std::runtime_error("Address-window readback mismatch");
            }
        }
        std::printf("%s: all %zu words matched\n", test.name, expected.size());
    }
}
