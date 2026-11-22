// Desktop d3d12_xs.dll: the two root-signature functions the inspected package DLLs import from the console
// Direct3D library. Both forward to the desktop d3d12.dll.
//
// The BVH builder adds flags 0x03000000 to every v1.1 descriptor it serializes, and all 52 of its embedded
// root signatures carry them. The desktop serializer rejects either bit with E_INVALIDARG, and clearing both
// let all 16 distinct layouts serialize and create on hardware and WARP (docs/experiments.md). The bits'
// console meaning has no public reference, so this shim clears exactly those two, keeps the caller's
// descriptor unchanged, reports the first time it does so, and returns every other result as d3d12.dll does.
#include <windows.h>
#include <d3d12.h>

#include <cstddef>
#include <cstdio>

namespace {

constexpr UINT kConsoleRootFlags = 0x03000000u;
static_assert(offsetof(D3D12_VERSIONED_ROOT_SIGNATURE_DESC, Desc_1_0) + offsetof(D3D12_ROOT_SIGNATURE_DESC, Flags) ==
              0x28);
static_assert(offsetof(D3D12_ROOT_SIGNATURE_DESC1, Flags) == offsetof(D3D12_ROOT_SIGNATURE_DESC, Flags));
static_assert(offsetof(D3D12_ROOT_SIGNATURE_DESC2, Flags) == offsetof(D3D12_ROOT_SIGNATURE_DESC, Flags));

volatile LONG reported;

}  // namespace

extern "C" HRESULT WINAPI xs_serialize_versioned_root_signature(const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* desc,
                                                                ID3DBlob** blob, ID3DBlob** error) {
    if (!desc || (static_cast<UINT>(desc->Desc_1_0.Flags) & kConsoleRootFlags) == 0)
        return D3D12SerializeVersionedRootSignature(desc, blob, error);
    // All three descriptor versions keep Flags at the same offset, so one copy covers them.
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC copy = *desc;
    copy.Desc_1_0.Flags =
        static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(static_cast<UINT>(copy.Desc_1_0.Flags) & ~kConsoleRootFlags);
    if (InterlockedExchange(&reported, 1) == 0)
        std::fprintf(stderr, "[x2w] d3d12_xs: cleared console root signature flags 0x%08x\n",
                     static_cast<UINT>(desc->Desc_1_0.Flags) & kConsoleRootFlags);
    return D3D12SerializeVersionedRootSignature(&copy, blob, error);
}

extern "C" HRESULT WINAPI xs_create_root_signature_deserializer(const void* data, SIZE_T size, REFIID iid,
                                                                void** object) {
    return D3D12CreateRootSignatureDeserializer(data, size, iid, object);
}
