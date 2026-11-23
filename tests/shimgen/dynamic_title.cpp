// A source-built, CRT-free stand-in for a PC GDK title's runtime calls: like xgameruntime.lib's thunks it
// imports no Gaming Runtime function, but loads xgameruntime.dll with LoadLibraryExW and resolves names with
// GetProcAddress. Run through x2w_launch --shims DIR, the launcher's loader hooks must route the load to the
// generated xgameruntime.dll shim (tools/shimgen.py --all-specs) and log each load and resolve.
// The exit code has one bit per check; 0x1ff when all pass. It holds no title code or data.
#include <windows.h>

#pragma runtime_checks("", off)

namespace {
enum class Mode : unsigned { Manual = 0 };
enum class Port : unsigned { Work = 0 };
using Init = HRESULT (*)();
using DeviceType = unsigned (*)();
using QueueCreate = HRESULT (*)(Mode, Mode, void**);
using QueueSubmit = HRESULT (*)(void*, Port, void*, void(CALLBACK*)(void*, bool));
using QueueDispatch = bool (*)(void*, Port, unsigned);
using QueueClose = void (*)(void*);
using LoadEx = HMODULE(WINAPI*)(LPCWSTR, HANDLE, DWORD);

volatile LONG ran;
void CALLBACK callback(void* context, bool canceled)
{
    if (!canceled) InterlockedAdd(&ran, static_cast<LONG>(reinterpret_cast<ULONG_PTR>(context)));
}
}  // namespace

extern "C" DWORD dynamic_entry(void*)
{
    unsigned result = 0;
    HMODULE runtime = LoadLibraryExW(L"xgameruntime.dll", nullptr, 0);
    if (runtime && GetProcAddress(runtime, "x2w_shimgen_dll")) result |= 0x1;  // our generated shim
    if (runtime && GetModuleHandleW(L"XGameRuntime.dll") == runtime) result |= 0x2;
    if (runtime && LoadLibraryA("XGAMERUNTIME") == runtime) result |= 0x4;
    auto init = reinterpret_cast<Init>(GetProcAddress(runtime, "XGameRuntimeInitialize"));
    if (init && init() == S_OK) result |= 0x8;
    auto device = reinterpret_cast<DeviceType>(GetProcAddress(runtime, "XSystemGetDeviceType"));
    if (device && device() == 7) result |= 0x10;  // XSystemDeviceType::XboxScarlettAnaconda
    if (!GetProcAddress(runtime, "X2WNotExported")) result |= 0x20;
    // A dynamically resolved loader function is hooked too.
    auto load = reinterpret_cast<LoadEx>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryExW"));
    if (load && load(L"xgameruntime.dll", nullptr, 0) == runtime) result |= 0x40;
    // x2w_gdk.dll (beside the shim) does the work: a manual task queue dispatches a callback.
    auto create = reinterpret_cast<QueueCreate>(GetProcAddress(runtime, "XTaskQueueCreate"));
    auto submit = reinterpret_cast<QueueSubmit>(GetProcAddress(runtime, "XTaskQueueSubmitCallback"));
    auto dispatch = reinterpret_cast<QueueDispatch>(GetProcAddress(runtime, "XTaskQueueDispatch"));
    auto close = reinterpret_cast<QueueClose>(GetProcAddress(runtime, "XTaskQueueCloseHandle"));
    void* queue = nullptr;
    if (create && submit && dispatch && close && create(Mode::Manual, Mode::Manual, &queue) == S_OK) {
        submit(queue, Port::Work, reinterpret_cast<void*>(5), callback);
        if (dispatch(queue, Port::Work, 0) && ran == 5) result |= 0x80;
        close(queue);
    }
    // A DLL no shim provides goes to the Windows loader.
    if (LoadLibraryW(L"x2w_no_such_dll_for_dynamic_title.dll") == nullptr) result |= 0x100;
    return result;
}
