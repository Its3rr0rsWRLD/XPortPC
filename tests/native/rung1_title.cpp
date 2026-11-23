// Rung 1 of the runtime ladder: a source-built, CRT-free stand-in for a console-style title that starts and
// exits cleanly through x2w_launch. It uses only DLL and function names that this repository's shims and
// tests already define: xmem.dll (XMemAlloc, XMemFree, XMemVirtualQuery) and d3d12_xs.dll
// (D3D12SerializeVersionedRootSignature) from the desktop shims, kernel32.dll from Windows, a name the xmem
// shim does not export (X2wNotInShim, from rung1_xmem.def) and x2w_missing.dll, which nothing provides
// (rung1_missing.def, with one import by ordinal).
// It has a TLS callback with an empty template and starts one worker thread, so the run log can show each
// startup milestone. The exit code records which steps behaved: 0x5f when all did.
//
// With X2W_RUNG1_CRASH=1 in the environment it writes through a null pointer after its last stub call, the
// crash control for the run log. It is never a title and holds no title code or data.
#include <windows.h>
#include <d3d12.h>
#include <intrin.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);
extern "C" __declspec(dllimport) BOOL XMemVirtualQuery(HANDLE process, LPCVOID address, void* buffer);
extern "C" __declspec(dllimport) int X2wNotInShim(int value);
extern "C" __declspec(dllimport) int X2wMissingFirst(int value);
extern "C" __declspec(dllimport) int X2wMissingSecond();
extern "C" __declspec(dllimport) int X2wMissingOrdinal();  // imported by ordinal 7 (rung1_missing.def)

namespace {
volatile LONG tls_attached;
volatile LONG worker_ran;

struct TlsDirectory {
    void* start;
    void* end;
    ULONG* index;
    PIMAGE_TLS_CALLBACK* callbacks;
    DWORD zero_fill;
    DWORD characteristics;
};

DWORD WINAPI worker(void*) {
    InterlockedExchange(&worker_ran, 1);
    return 0;
}
}  // namespace

extern "C" void NTAPI rung1_tls(PVOID, DWORD reason, PVOID) {
    if (reason == DLL_PROCESS_ATTACH) InterlockedIncrement(&tls_attached);
}

extern "C" ULONG rung1_tls_index;
ULONG rung1_tls_index;

#pragma section(".tlscb", read)
extern "C" __declspec(allocate(".tlscb")) PIMAGE_TLS_CALLBACK rung1_tls_callbacks[] = {rung1_tls, nullptr};

extern "C" const TlsDirectory _tls_used = {nullptr, nullptr, &rung1_tls_index, rung1_tls_callbacks, 0, 0};

extern "C" DWORD rung1_entry(void*) {
    DWORD code = 0x40;
    // xmem.dll: allocate, write, query and free one block through the desktop shim.
    auto* block = static_cast<volatile unsigned char*>(XMemAlloc(4096, 0));
    if (block) {
        block[0] = 0x5a;
        block[4095] = 0xa5;
        ULONGLONG query[8];
        __stosb(reinterpret_cast<unsigned char*>(query), 0, sizeof query);
        if (block[0] == 0x5a && block[4095] == 0xa5 && XMemVirtualQuery(GetCurrentProcess(), (void*)block, query))
            code |= 1;
        XMemFree((void*)block, 0);
    }
    // kernel32.dll: one worker thread, started and joined.
    if (HANDLE thread = CreateThread(nullptr, 0, worker, nullptr, 0, nullptr)) {
        if (WaitForSingleObject(thread, 10000) == WAIT_OBJECT_0 && worker_ran) code |= 2;
        CloseHandle(thread);
    }
    // d3d12_xs.dll: an empty v1.1 root signature with the console flag bits the shim clears.
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc;
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 0;
    desc.Desc_1_1.pParameters = nullptr;
    desc.Desc_1_1.NumStaticSamplers = 0;
    desc.Desc_1_1.pStaticSamplers = nullptr;
    desc.Desc_1_1.Flags = static_cast<D3D12_ROOT_SIGNATURE_FLAGS>(0x03000000);
    ID3DBlob* blob = nullptr;
    if (SUCCEEDED(D3D12SerializeVersionedRootSignature(&desc, &blob, nullptr)) && blob) {
        if (blob->GetBufferSize() != 0) code |= 4;
        blob->Release();
    }
    // Stubs return 0. X2wNotInShim names a DLL that exists without the function; x2w_missing.dll has no route.
    if (X2wNotInShim(1) == 0 && X2wMissingFirst(7) == 0 && X2wMissingFirst(8) == 0 && X2wMissingSecond() == 0
        && X2wMissingOrdinal() == 0)
        code |= 8;
    if (tls_attached == 1) code |= 0x10;
    char flag[4];
    if (GetEnvironmentVariableA("X2W_RUNG1_CRASH", flag, sizeof flag) == 1 && flag[0] == '1')
        *static_cast<volatile DWORD*>(nullptr) = code;
    return code;
}
