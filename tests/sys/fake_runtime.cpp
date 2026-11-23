// Stand-in for the public PC runtimes (GameInput, XAudio2, DirectStorage): same export names, sentinel results.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>

extern "C" {
__declspec(dllexport) HRESULT WINAPI GameInputCreate(void** out) {
    *out = reinterpret_cast<void*>(static_cast<uintptr_t>(0x1234));
    return S_OK;
}
// out = 0x100000000 + flags * 0x1000 + processor
__declspec(dllexport) HRESULT WINAPI XAudio2Create(void** out, UINT32 flags, UINT32 processor) {
    *out = reinterpret_cast<void*>(static_cast<uintptr_t>(0x100000000ull + static_cast<uint64_t>(flags) * 0x1000 + processor));
    return S_OK;
}
// out = the iid's Data1
__declspec(dllexport) HRESULT WINAPI DStorageGetFactory(REFIID iid, void** out) {
    *out = reinterpret_cast<void*>(static_cast<uintptr_t>(iid.Data1));
    return S_OK;
}
}
