// Checks the desktop d3d12_xs.dll against d3d12.dll with a synthetic v1.1 descriptor and no local inputs.
// The shim is loaded by path, as a launcher shim directory would supply it.
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {

using Serialize = HRESULT(WINAPI*)(const D3D12_VERSIONED_ROOT_SIGNATURE_DESC*, ID3DBlob**, ID3DBlob**);
using Deserializer = HRESULT(WINAPI*)(const void*, SIZE_T, REFIID, void**);

std::vector<unsigned char> bytes(ID3DBlob* blob) {
    const auto* data = static_cast<const unsigned char*>(blob->GetBufferPointer());
    return {data, data + blob->GetBufferSize()};
}

bool check(bool condition, const char* what) {
    std::printf("%s: %s\n", condition ? "ok" : "FAILED", what);
    return condition;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 2;
    HMODULE shim = LoadLibraryW(argv[1]);
    if (!shim) return 2;
    const auto serialize = reinterpret_cast<Serialize>(GetProcAddress(shim, "D3D12SerializeVersionedRootSignature"));
    const auto deserializer =
        reinterpret_cast<Deserializer>(GetProcAddress(shim, "D3D12CreateRootSignatureDeserializer"));
    bool passed = check(serialize && deserializer, "both exports resolve by name");
    if (!passed) return 1;

    D3D12_ROOT_PARAMETER1 parameter{};
    parameter.ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    parameter.Constants.Num32BitValues = 4;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 1;
    desc.Desc_1_1.pParameters = &parameter;
    desc.Desc_1_1.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;

    ComPtr<ID3DBlob> reference;
    passed &= check(SUCCEEDED(D3D12SerializeVersionedRootSignature(&desc, &reference, nullptr)), "d3d12 reference");
    const auto expected = bytes(reference.Get());

    ComPtr<ID3DBlob> plain;
    passed &= check(serialize(&desc, &plain, nullptr) == S_OK && bytes(plain.Get()) == expected,
                    "desktop flags give the d3d12 bytes");

    for (const UINT console : {0x01000000u, 0x02000000u, 0x03000000u}) {
        D3D12_VERSIONED_ROOT_SIGNATURE_DESC tagged = desc;
        tagged.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(
            static_cast<UINT>(desc.Desc_1_1.Flags) | console);
        const D3D12_VERSIONED_ROOT_SIGNATURE_DESC before = tagged;
        ComPtr<ID3DBlob> direct;
        const HRESULT desktop = D3D12SerializeVersionedRootSignature(&tagged, &direct, nullptr);
        ComPtr<ID3DBlob> blob;
        const HRESULT result = serialize(&tagged, &blob, nullptr);
        const std::string name = "console bits 0x" + std::to_string(console >> 24) + "000000";
        passed &= check(desktop == E_INVALIDARG && !direct, (name + ": d3d12 alone rejects").c_str());
        passed &= check(result == S_OK && blob && bytes(blob.Get()) == expected,
                        (name + ": shim clears only those bits").c_str());
        passed &= check(std::memcmp(&before, &tagged, sizeof before) == 0, (name + ": caller descriptor unchanged").c_str());
    }

    D3D12_VERSIONED_ROOT_SIGNATURE_DESC invalid = desc;
    invalid.Version = static_cast<D3D_ROOT_SIGNATURE_VERSION>(0x99);
    invalid.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(0x03000000u);
    ComPtr<ID3DBlob> direct_invalid;
    ComPtr<ID3DBlob> shim_invalid;
    const HRESULT desktop_invalid = D3D12SerializeVersionedRootSignature(&invalid, &direct_invalid, nullptr);
    invalid.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(0);
    const HRESULT desktop_invalid_clear = D3D12SerializeVersionedRootSignature(&invalid, &direct_invalid, nullptr);
    invalid.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(0x03000000u);
    const HRESULT shim_result = serialize(&invalid, &shim_invalid, nullptr);
    passed &= check(FAILED(desktop_invalid_clear) && shim_result == desktop_invalid_clear && !shim_invalid,
                    "an unknown version still fails with the d3d12 result");
    (void)desktop_invalid;

    ComPtr<ID3DBlob> tagged_blob;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC tagged = desc;
    tagged.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(static_cast<UINT>(desc.Desc_1_1.Flags) | 0x03000000u);
    serialize(&tagged, &tagged_blob, nullptr);
    ComPtr<ID3D12VersionedRootSignatureDeserializer> reader;
    HRESULT read = deserializer(tagged_blob->GetBufferPointer(), tagged_blob->GetBufferSize(), IID_PPV_ARGS(&reader));
    // The legacy deserializer reports the v1.0 view of the same blob.
    ComPtr<ID3D12RootSignatureDeserializer> legacy;
    HRESULT legacy_read =
        deserializer(tagged_blob->GetBufferPointer(), tagged_blob->GetBufferSize(), IID_PPV_ARGS(&legacy));
    passed &= check(SUCCEEDED(legacy_read) && legacy &&
                        legacy->GetRootSignatureDesc()->Flags == D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT &&
                        legacy->GetRootSignatureDesc()->NumParameters == 1,
                    "deserializer reads the shim's blob back with desktop flags");
    ComPtr<ID3D12RootSignatureDeserializer> none;
    const unsigned char junk[16] = {};
    passed &= check(FAILED(deserializer(junk, sizeof junk, IID_PPV_ARGS(&none))) && !none,
                    "deserializer rejects bytes without a root signature");
    (void)read;
    return passed ? 0 : 1;
}
