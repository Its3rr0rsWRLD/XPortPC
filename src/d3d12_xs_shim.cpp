// Desktop d3d12_xs.dll: the graphics shim. It exports the two root-signature functions the package
// DLLs import by name, and device creation over desktop D3D12 through the wrappers in
// d3d12_xs_wrap.cpp (docs/design/runtime.md, section 3).
// Observed call sites (docs/experiments.md):
//   D3D12SerializeVersionedRootSignature: XboxBvhBuilder.dll (0xc2d0/0xc32f) copies a 48-byte
//     descriptor, sets console flag bits 0x03000000 at +0x28, and passes a null error output.
//   D3D12CreateRootSignatureDeserializer: amd_fidelityfx_upscaler_xbox.dll (0x4f88) reads a
//     serialized root signature from an embedded container and retrieves the descriptor interface.
#include <d3d12.h>
#include <d3d12sdklayers.h>

#include "d3d12_xs_api.h"
#include "d3d12_xs_wrap.h"

#include <cstddef>
#include <cstdint>

namespace {
// Observed console root-signature flag bits set by XboxBvhBuilder.dll.
// Unobserved bits are left untouched so desktop d3d12.dll still rejects unknown flags.
constexpr std::uint32_t observed_console_flags = 0x03000000u;

static_assert(offsetof(D3D12_VERSIONED_ROOT_SIGNATURE_DESC, Desc_1_0) +
              offsetof(D3D12_ROOT_SIGNATURE_DESC, Flags) == 0x28);
static_assert(offsetof(D3D12_VERSIONED_ROOT_SIGNATURE_DESC, Desc_1_1) +
              offsetof(D3D12_ROOT_SIGNATURE_DESC1, Flags) == 0x28);
}

extern "C" HRESULT WINAPI d3d12_xs_SerializeVersionedRootSignature(
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* root_signature,
    ID3DBlob** blob,
    ID3DBlob** error_blob)
{
    if (!root_signature) {
        return D3D12SerializeVersionedRootSignature(root_signature, blob, error_blob);
    }
    if (root_signature->Version == D3D_ROOT_SIGNATURE_VERSION_1_1) {
        const auto flags = static_cast<std::uint32_t>(root_signature->Desc_1_1.Flags);
        if (flags & observed_console_flags) {
            D3D12_VERSIONED_ROOT_SIGNATURE_DESC copy = *root_signature;
            copy.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(flags & ~observed_console_flags);
            return D3D12SerializeVersionedRootSignature(&copy, blob, error_blob);
        }
    } else if (root_signature->Version == D3D_ROOT_SIGNATURE_VERSION_1_0) {
        const auto flags = static_cast<std::uint32_t>(root_signature->Desc_1_0.Flags);
        if (flags & observed_console_flags) {
            D3D12_VERSIONED_ROOT_SIGNATURE_DESC copy = *root_signature;
            copy.Desc_1_0.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(flags & ~observed_console_flags);
            return D3D12SerializeVersionedRootSignature(&copy, blob, error_blob);
        }
    }
    return D3D12SerializeVersionedRootSignature(root_signature, blob, error_blob);
}

extern "C" HRESULT WINAPI d3d12_xs_CreateRootSignatureDeserializer(
    LPCVOID src_data,
    SIZE_T src_data_size_in_bytes,
    REFIID deserializer_interface,
    void** deserializer)
{
    return D3D12CreateRootSignatureDeserializer(
        src_data, src_data_size_in_bytes, deserializer_interface, deserializer);
}

// Device creation, as desktop D3D12CreateDevice: a null output only checks support and is forwarded.
// Otherwise the desktop device is created and handed out wrapped through riid; an unknown riid is
// logged and fails with E_NOINTERFACE.
extern "C" HRESULT WINAPI d3d12_xs_CreateDevice(IUnknown* adapter, D3D_FEATURE_LEVEL minimum_level, REFIID riid,
                                                void** device)
{
    const void* caller = X2W_RETURN_ADDRESS();
    if (!device) return D3D12CreateDevice(adapter, minimum_level, riid, nullptr);
    *device = nullptr;
    ID3D12Device* real = nullptr;
    const HRESULT hr = D3D12CreateDevice(adapter, minimum_level, IID_PPV_ARGS(&real));
    if (FAILED(hr)) return hr;
    return d3d12_xs::wrap_device(real, riid, device, caller);
}

// The debug layer is the desktop one (ID3D12Debug and later), returned unwrapped.
extern "C" HRESULT WINAPI d3d12_xs_GetDebugInterface(REFIID riid, void** debug)
{
    return D3D12GetDebugInterface(riid, debug);
}

extern "C" X2W_GFX_API HRESULT WINAPI X2WGfxCreateSwapChainForHwnd(IUnknown* queue, HWND window,
    const DXGI_SWAP_CHAIN_DESC1* desc, const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fullscreen_desc,
    IDXGIOutput* restrict_to_output, REFIID riid, void** swap_chain)
{
    return d3d12_xs::create_swap_chain_for_hwnd(queue, window, desc, fullscreen_desc, restrict_to_output, riid,
                                                swap_chain, X2W_RETURN_ADDRESS());
}
