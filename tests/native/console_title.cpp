// Source-built, CRT-free title that imports every name of the console libraries xcrdapi.dll, chad.dll, xapu.dll,
// acphal.dll and xg_xs.dll and the four newer xmem.dll names, by those DLL names, and checks what they do under
// x2w_launch (tests/native/console_check.py): every import must route to a shim, and every call must succeed
// safely. Signatures of the audio and texture libraries are assumptions (docs/design/runtime.md, "Console audio
// hardware: silent"); this program only relies on the behaviour that document states.
// Exit code: 0 when every step passed, else the number of the first step that failed. Stdout: one "step=<n>" line each.
#include <windows.h>

#pragma runtime_checks("", off)

typedef uintptr_t U;
#define X2W_IMPORT(ret, name) extern "C" __declspec(dllimport) ret name(U, U, U, U, U, U)
X2W_IMPORT(HRESULT, XDspActivate);
X2W_IMPORT(HRESULT, XDspConnectWithMaximumStreamLimit);
X2W_IMPORT(HRESULT, XDspDeactivate);
X2W_IMPORT(HRESULT, XDspDisconnect);
X2W_IMPORT(HRESULT, XDspSubmitCommand);
X2W_IMPORT(HRESULT, XApuConnect);
X2W_IMPORT(HRESULT, XApuDequeueResult);
X2W_IMPORT(HRESULT, XApuDisconnect);
X2W_IMPORT(HRESULT, XApuEnqueueCommand);
X2W_IMPORT(unsigned, XApuGetResultCount);
X2W_IMPORT(HRESULT, AcpHalAllocateShapeContexts);
X2W_IMPORT(HRESULT, AcpHalCreate);
X2W_IMPORT(HRESULT, AcpHalReleaseShapeContexts);
X2W_IMPORT(U, ApuAlloc);
X2W_IMPORT(U, ApuCreateHeap);
X2W_IMPORT(HRESULT, ApuFree);
X2W_IMPORT(BOOL, ApuIsVirtualAddressValid);
X2W_IMPORT(U, ApuMapApuAddress);
X2W_IMPORT(U, ApuMapVirtualAddress);
X2W_IMPORT(HRESULT, XGCreateTextureComputer);
X2W_IMPORT(unsigned, XGSuggestSwizzleMode);
extern "C" __declspec(dllimport) HRESULT WINAPI DStorageGetFactory(const IID& iid, void** out);
extern "C" __declspec(dllimport) void* WINAPI XMemVirtualAlloc(void*, SIZE_T, DWORD, DWORD);
extern "C" __declspec(dllimport) BOOL WINAPI XMemTransferMemory(ULONG_PTR, ULONG_PTR, ULONG_PTR, ULONG_PTR);
extern "C" __declspec(dllimport) BOOL WINAPI XMemMapPhysicalPagesScatter(void**, ULONG_PTR, ULONG_PTR*);
extern "C" __declspec(dllimport) BOOL WINAPI XMemIsToolsMemAvailable(void);
extern "C" __declspec(dllimport) BOOL WINAPI XMemAllocatePhysicalPages(DWORD, ULONG_PTR*, ULONG_PTR*);
extern "C" __declspec(dllimport) BOOL WINAPI XMemFreePhysicalPages(ULONG_PTR, ULONG_PTR*);

namespace {
const IID unknown_iid = {0, 0, 0, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};
HANDLE out_handle;
int failed_step;
int step;

void check(bool ok) {
    ++step;
    char text[24] = "step=0\n";
    text[5] = static_cast<char>('0' + step / 10);
    text[6] = static_cast<char>('0' + step % 10);
    text[7] = ok ? '\n' : '!';
    text[8] = '\n';
    DWORD written = 0;
    WriteFile(out_handle, text, ok ? 8 : 9, &written, nullptr);
    if (!ok && !failed_step) failed_step = step;
}

struct VTable {
    HRESULT(STDMETHODCALLTYPE* query)(void*, const IID&, void**);
    ULONG(STDMETHODCALLTYPE* add_ref)(void*);
    ULONG(STDMETHODCALLTYPE* release)(void*);
    HRESULT(STDMETHODCALLTYPE* slot[64])(void*, U, U, U);
};
struct Object {
    const VTable* vtable;
};
}  // namespace

extern "C" DWORD console_entry(void*) {
    out_handle = GetStdHandle(STD_OUTPUT_HANDLE);
    // xcrdapi.dll: forwarded to x2w_sys.dll: S_OK with a DirectStorage runtime, else its fallback status.
    void* factory = reinterpret_cast<void*>(1);
    const IID iid = {0x6924ea0c, 0xc3cd, 0x4826, {0xb1, 0x0a, 0xf6, 0x4f, 0x4e, 0xd9, 0x27, 0xc1}};
    const HRESULT status = DStorageGetFactory(iid, &factory);
    check(status == 0 || status == static_cast<HRESULT>(0xA2570002));  // 1
    check(status != 0 || factory != nullptr);                         // 2
    check(status == 0 || factory == nullptr);                         // 3

    // chad.dll
    U slot = 0;
    check(XDspConnectWithMaximumStreamLimit(reinterpret_cast<U>(&slot), 0, 0, 0, 0, 0) == 0 && slot != 0);  // 4
    U busy = 0x1234;
    check(XDspConnectWithMaximumStreamLimit(reinterpret_cast<U>(&busy), 0, 0, 0, 0, 0) == 0 && busy == 0x1234);  // 5
    check(XDspConnectWithMaximumStreamLimit(0, 7, 8, 9, 0, 0) == 0);  // 6
    check(XDspActivate(slot, 1, 2, 3, 0, 0) == 0 && XDspSubmitCommand(slot, 1, 2, 3, 0, 0) == 0 &&
          XDspDeactivate(slot, 0, 0, 0, 0, 0) == 0 && XDspDisconnect(slot, 0, 0, 0, 0, 0) == 0);  // 7
    // A read-only output slot is left alone.
    auto* page = static_cast<U*>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READONLY));
    check(page && XDspConnectWithMaximumStreamLimit(reinterpret_cast<U>(page), 0, 0, 0, 0, 0) == 0 && *page == 0);  // 8

    // xapu.dll
    U apu = 0;
    check(XApuConnect(reinterpret_cast<U>(&apu), 0, 0, 0, 0, 0) == 0 && apu != 0);  // 9
    check(XApuGetResultCount(apu, 0, 0, 0, 0, 0) == 0 && XApuDequeueResult(apu, 0, 0, 0, 0, 0) == 0);  // 10
    check(XApuEnqueueCommand(apu, 1, 2, 3, 0, 0) == 0 && XApuDisconnect(apu, 0, 0, 0, 0, 0) == 0);  // 11

    // acphal.dll
    U hal = 0, shapes = 0;
    check(AcpHalCreate(reinterpret_cast<U>(&hal), 0, 0, 0, 0, 0) == 0 && hal != 0);  // 12
    check(AcpHalAllocateShapeContexts(reinterpret_cast<U>(&shapes), 4, 0, 0, 0, 0) == 0 && shapes != 0 &&
          AcpHalReleaseShapeContexts(shapes, 0, 0, 0, 0, 0) == 0);  // 13
    const U block = ApuAlloc(0x20000, 0, 0, 0, 0, 0);
    check(block != 0);  // 14
    if (block) *reinterpret_cast<volatile char*>(block + 0x1ffff) = 1;  // the whole block is writable
    check(ApuIsVirtualAddressValid(block, 0, 0, 0, 0, 0) && ApuIsVirtualAddressValid(block + 0x1000, 0, 0, 0, 0, 0) &&
          !ApuIsVirtualAddressValid(0x10, 0, 0, 0, 0, 0));  // 15
    check(ApuMapVirtualAddress(block + 8, 0, 0, 0, 0, 0) == block + 8 && ApuMapApuAddress(0x77000, 0, 0, 0, 0, 0) == 0x77000);  // 16
    const U heap = ApuCreateHeap(0x40000, 0, 0, 0, 0, 0);
    check(heap != 0 && ApuIsVirtualAddressValid(heap + 0x3ffff, 0, 0, 0, 0, 0));  // 17
    check(ApuFree(block, 0, 0, 0, 0, 0) == 0 && !ApuIsVirtualAddressValid(block, 0, 0, 0, 0, 0) &&
          ApuFree(heap, 0, 0, 0, 0, 0) == 0);  // 18

    // xg_xs.dll
    Object* computer = nullptr;
    check(XGCreateTextureComputer(0, reinterpret_cast<U>(&computer), 0, 0, 0, 0) == 0 && computer && computer->vtable);  // 19
    if (computer && computer->vtable) {
        void* again = nullptr;
        check(computer->vtable->slot[5](computer, 1, 2, 3) == E_NOTIMPL && computer->vtable->slot[63](computer, 0, 0, 0) == E_NOTIMPL);  // 20
        check(computer->vtable->query(computer, unknown_iid, &again) == 0 && again == computer);  // 21
        check(computer->vtable->add_ref(computer) == 3 && computer->vtable->release(computer) == 2 &&
              computer->vtable->release(computer) == 1 && computer->vtable->release(computer) == 0);  // 22
    } else {
        check(false);
        check(false);
        check(false);
    }
    check(XGSuggestSwizzleMode(0, 0, 0, 0, 0, 0) == 0);  // 23
    check(XGCreateTextureComputer(0, 0, 0, 0, 0, 0) == E_POINTER);  // 24

    // xmem.dll
    check(!XMemIsToolsMemAvailable() && XMemTransferMemory(1, 2, 3, 4));  // 25
    ULONG_PTR pages[3] = {};
    ULONG_PTR count = 3;
    check(XMemAllocatePhysicalPages(MEM_LARGE_PAGES, &count, pages) && count == 3);  // 26
    auto* area = static_cast<unsigned char*>(XMemVirtualAlloc(nullptr, 0x20000, MEM_RESERVE | 0x40000000, PAGE_NOACCESS));
    check(area != nullptr && (reinterpret_cast<U>(area) & 0xffff) == 0);  // 27
    void* where[2] = {area, area + 0x10000};
    ULONG_PTR chosen[2] = {pages[1], pages[1]};
    check(area && XMemMapPhysicalPagesScatter(where, 2, chosen));  // 28
    if (area) area[3] = 9;
    check(area && area[0x10003] == 9 && XMemMapPhysicalPagesScatter(where, 2, nullptr) && !XMemMapPhysicalPagesScatter(nullptr, 1, chosen));  // 29
    XMemFreePhysicalPages(count, pages);
    ExitProcess(static_cast<UINT>(failed_step));
    return 0;
}
