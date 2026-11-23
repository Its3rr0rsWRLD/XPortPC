// Source-built title without a C runtime that imports gameinput.dll!GameInputCreate, as a console GDK title does,
// and calls the interface through the v0 vtable slots (src/sys/sys_gameinput_v0.h). Run under x2w_launch with the
// shims directory, which holds x2w's gameinput.dll (tests/native/gameinput_check.py).
//
// Exit code 0 when every step answered as the v0 facade does; otherwise the bits of the failed steps:
//   0x1 GameInputCreate      0x2 GetCurrentTimestamp nonzero and increasing    0x4 GetCurrentReading(gamepad):
//   S_OK with a reading whose GetGamepadState succeeds, or GAMEINPUT_E_READING_NOT_FOUND with no pad
//   0x8 RegisterDeviceCallback (blocking) gives a token, the callback ran once per pad (stdout pads=N)
//   0x10 an unknown slot (40) returns E_NOTIMPL   0x20 UnregisterCallback true   0x40 CreateDispatcher + Dispatch false
//   0x80 GetCurrentReading(keyboard) is READING_NOT_FOUND   0x100 QueryInterface + Release
// X2W_GI_MODE=fastfail: after the steps, RaiseFailFastException (the launcher logs it and the final summary).
// X2W_GI_MODE=thread: after the steps, a thread that starts in a Windows function faults there unhandled.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) HRESULT WINAPI GameInputCreate(void** out);

namespace {

using u64 = unsigned long long;
void** vt(void* object) { return *static_cast<void***>(object); }

template <class R, class... A>
R call(void* object, int slot, A... args) {
    return reinterpret_cast<R(STDMETHODCALLTYPE*)(void*, A...)>(vt(object)[slot])(object, args...);
}

volatile long g_pads;
void CALLBACK on_device(u64, void* context, void* device, u64, unsigned current, unsigned) {
    if (context == &g_pads && device && (current & 1)) InterlockedIncrement(&g_pads);
}

HANDLE out_handle;
void put(const char* text) {
    DWORD written = 0, length = 0;
    while (text[length]) ++length;
    WriteFile(out_handle, text, length, &written, nullptr);
}

bool mode_is(const char* want) {
    char mode[16];
    const DWORD length = GetEnvironmentVariableA("X2W_GI_MODE", mode, sizeof mode);
    if (length == 0 || length >= sizeof mode) return false;
    for (DWORD i = 0; i <= length; ++i)
        if (mode[i] != want[i]) return false;
    return true;
}

constexpr HRESULT kReadingNotFound = static_cast<HRESULT>(0x838A0003);
const GUID kSomeIid = {0x11be2a7e, 0x4254, 0x445a, {0x9c, 0x09, 0xff, 0xc4, 0x0f, 0x00, 0x69, 0x18}};

}  // namespace

extern "C" DWORD gameinput_entry(void*) {
    out_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD failed = 0x1ff;
    void* input = nullptr;
    if (GameInputCreate(&input) == S_OK && input) failed &= ~0x1u;
    if (!input) return failed;

    const u64 t0 = call<u64>(input, 3);
    Sleep(2);
    const u64 t1 = call<u64>(input, 3);
    if (t0 && t1 > t0) failed &= ~0x2u;

    void* reading = nullptr;
    const HRESULT hr = call<HRESULT>(input, 4, 0x40000u, static_cast<void*>(nullptr), &reading);
    if (hr == S_OK && reading) {
        struct { unsigned buttons; float f[6]; } state = {};
        if (call<bool>(reading, 22, &state) && call<unsigned>(reading, 3) == 0x40000u) failed &= ~0x4u;
        void* next = reinterpret_cast<void*>(1);
        call<HRESULT>(input, 5, reading, 0x40000u, static_cast<void*>(nullptr), &next);  // GetNextReading
        if (next) call<ULONG>(next, 2);
        call<ULONG>(reading, 2);
        put("reading=ok\n");
    } else if (hr == kReadingNotFound && !reading) {
        failed &= ~0x4u;
        put("reading=none\n");
    }

    u64 token = 0;
    using Callback = void(CALLBACK*)(u64, void*, void*, u64, unsigned, unsigned);
    const HRESULT registered = call<HRESULT>(input, 9, static_cast<void*>(nullptr), 0x40000u, 0xffffffu, 2u,
                                             static_cast<void*>(const_cast<long*>(&g_pads)), static_cast<Callback>(&on_device), &token);
    if (registered == S_OK && token) failed &= ~0x8u;
    put(g_pads == 0 ? "pads=0\n" : g_pads == 1 ? "pads=1\n" : "pads=many\n");

    if (call<HRESULT>(input, 40, 0x1234ull, 0x5678ull, 0x9abcull) == E_NOTIMPL) failed &= ~0x10u;
    if (call<bool>(input, 13, token, 1000ull)) failed &= ~0x20u;

    void* dispatcher = nullptr;
    if (call<HRESULT>(input, 14, &dispatcher) == S_OK && dispatcher && !call<bool>(dispatcher, 3, 0ull)) {
        call<ULONG>(dispatcher, 2);
        failed &= ~0x40u;
    }
    reading = reinterpret_cast<void*>(1);
    if (call<HRESULT>(input, 4, 0x10u, static_cast<void*>(nullptr), &reading) == kReadingNotFound && !reading)
        failed &= ~0x80u;

    void* same = nullptr;
    if (call<HRESULT>(input, 0, &kSomeIid, &same) == S_OK && same == input) {
        call<ULONG>(same, 2);
        failed &= ~0x100u;
    }
    call<void>(input, 21, 0u);  // SetFocusPolicy
    call<ULONG>(input, 2);

    if (mode_is("fastfail")) {
        EXCEPTION_RECORD record = {};
        record.ExceptionCode = 0xc0000409;
        RaiseFailFastException(&record, nullptr, 0);
    }
    if (mode_is("thread")) {
        // lstrlenW handles its own faults; ntdll's wcslen does not. The thread starts in ntdll and never runs
        // this image's code, so the fault has no mapped frames to report.
        auto start = reinterpret_cast<LPTHREAD_START_ROUTINE>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "wcslen"));
        HANDLE thread = CreateThread(nullptr, 0, start, reinterpret_cast<void*>(static_cast<ULONG_PTR>(0x10)), 0, nullptr);
        if (thread) WaitForSingleObject(thread, 10000);
        return 0x77;
    }
    return failed;
}
