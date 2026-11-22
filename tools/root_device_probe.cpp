#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <fcntl.h>
#include <io.h>
#include <cstdio>
#include <iostream>
#include <iterator>
#include <string_view>
#include <vector>
using Microsoft::WRL::ComPtr;

namespace {
unsigned highest_shader_model(ID3D12Device* device)
{
    D3D12_FEATURE_DATA_SHADER_MODEL sm{D3D_SHADER_MODEL_6_5};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &sm, sizeof(sm))))
        return static_cast<unsigned>(sm.HighestShaderModel);
    sm.HighestShaderModel = D3D_SHADER_MODEL_6_0;
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &sm, sizeof(sm))))
        return static_cast<unsigned>(sm.HighestShaderModel);
    return 0;
}
}

int main(int argc, char** argv)
{
    bool warpOnly = false;
    bool computePso = false;
    for (int i = 1; i < argc; ++i) {
        std::string_view arg(argv[i]);
        if (arg == "--warp-only" && !warpOnly) warpOnly = true;
        else if (arg == "--compute-pso" && !computePso) computePso = true;
        else return 1;
    }
    _setmode(_fileno(stdin), _O_BINARY);
    std::vector<char> input{std::istreambuf_iterator<char>(std::cin), {}};
    if (input.empty() || std::cin.bad()) return 2;

    ComPtr<ID3D12VersionedRootSignatureDeserializer> reader;
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* source = nullptr;
    if (!computePso) {
        if (FAILED(D3D12CreateVersionedRootSignatureDeserializer(
            input.data(), input.size(), IID_PPV_ARGS(&reader)))) return 2;
        source = reader->GetUnconvertedRootSignatureDesc();
        if (!source || source->Version != D3D_ROOT_SIGNATURE_VERSION_1_1) return 3;
    }

    ComPtr<IDXGIFactory6> factory;
    ComPtr<IDXGIAdapter1> hardware, warp;
    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory))) ||
        FAILED(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)))) return 4;
    DXGI_ADAPTER_DESC1 adapter{};
    ComPtr<ID3D12Device> gpuDevice, warpDevice;
    if (!warpOnly) {
        for (UINT index = 0; ; ++index) {
            if (FAILED(factory->EnumAdapterByGpuPreference(index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                    IID_PPV_ARGS(hardware.ReleaseAndGetAddressOf())))) {
                std::fputs("No compatible hardware adapter. Use --warp-only for WARP.\n", stderr);
                return 5;
            }
            if (FAILED(hardware->GetDesc1(&adapter))) return 5;
            if (!(adapter.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
                SUCCEEDED(D3D12CreateDevice(hardware.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&gpuDevice)))) break;
        }
    }
    if (FAILED(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&warpDevice)))) return 6;

    if (computePso) {
        std::printf("{\"bytes\":%zu", input.size());
        if (gpuDevice) std::printf(",\"adapter_id\":\"%04x:%04x\"", adapter.VendorId, adapter.DeviceId);
        for (auto* device : {gpuDevice.Get(), warpDevice.Get()}) {
            if (!device) continue;
            const char* name = device == gpuDevice.Get() ? "hardware" : "warp";
            std::printf(",\"%s_shader_model\":\"0x%x\"", name, highest_shader_model(device));
            ComPtr<ID3D12RootSignature> root;
            const HRESULT root_hr = device->CreateRootSignature(0, input.data(), input.size(), IID_PPV_ARGS(&root));
            std::printf(",\"%s_root\":\"0x%08lx\"", name, static_cast<unsigned long>(root_hr));
            if (SUCCEEDED(root_hr)) {
                D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
                desc.pRootSignature = root.Get();
                desc.CS = {input.data(), input.size()};
                ComPtr<ID3D12PipelineState> pipeline;
                const HRESULT pso_hr = device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pipeline));
                std::printf(",\"%s_pso\":\"0x%08lx\"", name, static_cast<unsigned long>(pso_hr));
            }
        }
        std::puts("}");
        return 0;
    }

    constexpr unsigned observed = 0x03000000;
    unsigned original = source->Desc_1_1.Flags;
    for (unsigned clear : {0u, 0x01000000u, 0x02000000u, observed}) {
        if (clear & ~original) continue;
        auto descriptor = *source;
        descriptor.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(original & ~clear);
        ComPtr<ID3DBlob> serialized;
        HRESULT serialize = D3D12SerializeVersionedRootSignature(&descriptor, &serialized, nullptr);
        std::printf("{\"remaining_flags\":%u,\"cleared\":%u,\"serialize\":\"0x%08lx\"",
                    original & ~clear, clear, static_cast<unsigned long>(serialize));
        if (gpuDevice) std::printf(",\"adapter_id\":\"%04x:%04x\"", adapter.VendorId, adapter.DeviceId);
        if (SUCCEEDED(serialize)) {
            for (auto* device : {gpuDevice.Get(), warpDevice.Get()}) {
                if (!device) continue;
                ComPtr<ID3D12RootSignature> root;
                HRESULT hr = device->CreateRootSignature(0, serialized->GetBufferPointer(),
                    serialized->GetBufferSize(), IID_PPV_ARGS(&root));
                std::printf(",\"%s\":\"0x%08lx\"", device == gpuDevice.Get() ? "hardware" : "warp",
                            static_cast<unsigned long>(hr));
            }
        }
        std::puts("}");
    }
}
