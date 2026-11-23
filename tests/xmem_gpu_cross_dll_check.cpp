#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <cstdint>
#include <cstdio>
#include "test_guard.h"

using Microsoft::WRL::ComPtr;

using ClientFn = int32_t (*)(void*, uint64_t*);

int main(int argc, char* argv[])
{
    test_guard::install("xmem_gpu_cross_dll_check", 25);  // below the ctest TIMEOUT (CMakeLists.txt)
    const wchar_t* client_dll_path = L"xmem_gpu_client.dll";
    wchar_t path_buffer[MAX_PATH]{};
    if (argc > 1) {
        MultiByteToWideChar(CP_UTF8, 0, argv[1], -1, path_buffer, MAX_PATH);
        client_dll_path = path_buffer;
    }

    ComPtr<IDXGIFactory4> factory;
    ComPtr<IDXGIAdapter> adapter;
    ComPtr<ID3D12Device> device;

    if (FAILED(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory))) ||
        FAILED(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter))) ||
        FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) {
        std::fputs("Skipping check: WARP device could not be created\n", stderr);
        return 77;
    }

    HMODULE client_mod = LoadLibraryW(client_dll_path);
    if (!client_mod) {
        std::fprintf(stderr, "Failed to load client library %ls: %lu\n", client_dll_path, GetLastError());
        return 1;
    }

    auto client_round_trip = reinterpret_cast<ClientFn>(GetProcAddress(client_mod, "ClientTitleGpuRoundTrip"));
    if (!client_round_trip) {
        std::fputs("Failed to locate ClientTitleGpuRoundTrip export\n", stderr);
        FreeLibrary(client_mod);
        return 2;
    }

    uint64_t translated_addr = 0;
    const int32_t rc = client_round_trip(device.Get(), &translated_addr);
    FreeLibrary(client_mod);

    if (rc != 0 || translated_addr == 0) {
        std::fprintf(stderr, "Client round-trip failed with code %d, translated_addr 0x%llx\n", rc, static_cast<unsigned long long>(translated_addr));
        return 3;
    }

    std::puts("Cross-DLL Title GPU registry round trip succeeded.");
    return 0;
}
