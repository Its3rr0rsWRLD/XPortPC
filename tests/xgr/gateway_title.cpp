// Drives the xgameruntime.dll gateway (shims\x2w_xgr.dll) the way a PC GDK title's static xgameruntime.lib does:
// InitializeApiImplEx2, QueryApiImpl(CLSID, IID), then a call through the object's vtable and Release. Built
// with only the public flat-API types (src/gdk/x2w_gdk_types.h); the gateway is loaded by path (argv[1]).
//
// Usage: gateway_title x2w_xgr.dll [strict|inferred]
//   default  unknown CLSIDs and IIDs get logging fallback objects; unknown and inferred slots answer failure codes,
//            never fault and never touch their arguments; the traced XUser paths work (exit 0 when every check passes).
//   inferred X2W_XGR_INFERRED=1 (set by the caller): the inferred XNetworking/XUser slots are served.
//   strict   X2W_XGR_STRICT=1 (set by the caller): an unlisted query is refused with 0x80070032.
// The Python driver (gateway_check.py) also reads this process's stderr for the gateway's log lines.
#include <cstdio>
#include <cstring>
#include <initializer_list>

#include "x2w_gdk_types.h"

namespace {

int failures = 0;
bool g_inferred = false;  // argv[2] == "inferred": the run with X2W_XGR_INFERRED=1
#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);      \
            ++failures;                                                      \
        }                                                                    \
    } while (0)
#define CHECK_HR(expr, want)                                                                            \
    do {                                                                                                \
        const HRESULT got_ = (expr);                                                                    \
        if (got_ != static_cast<HRESULT>(want)) {                                                       \
            std::printf("FAIL %s:%d: %s -> 0x%08lx, want 0x%08lx\n", __FILE__, __LINE__, #expr,         \
                        static_cast<unsigned long>(got_), static_cast<unsigned long>(want));            \
            ++failures;                                                                                 \
        }                                                                                               \
    } while (0)

constexpr HRESULT notimpl = static_cast<HRESULT>(0x80004001L);
constexpr HRESULT not_supported = static_cast<HRESULT>(0x80070032L);
constexpr HRESULT no_default_user = static_cast<HRESULT>(0x89245106L);

// CLSID == IID for XThreading, XUser (tools/xgr/interfaces.toml).
const GUID clsid_threading = {0x073b7dcb, 0x1fcf, 0x4030, {0x94, 0xbe, 0xe3, 0xc9, 0xeb, 0x62, 0x34, 0x28}};
const GUID clsid_user = {0x01acd177, 0x91f9, 0x4763, {0xa3, 0x8e, 0xcc, 0xbb, 0x55, 0xce, 0x32, 0xe0}};
const GUID iid_gamertag = {0xcef4fac0, 0x7676, 0x4a94, {0xa1, 0x19, 0x4c, 0x43, 0xf9, 0xeb, 0x5b, 0x74}};
const GUID clsid_networking = {0x37e56907, 0x2f10, 0x41e8, {0xb7, 0x2f, 0x36, 0xed, 0xb1, 0x85, 0x33, 0x1a}};
const GUID iid_networking = {0xbf2346b2, 0x39af, 0x4658, {0xb5, 0xea, 0x44, 0x71, 0x3c, 0x7e, 0x83, 0xb3}};
// Made up for this test: no such class or interface exists.
const GUID clsid_nothing = {0x5e3a0c11, 0x0b0b, 0x4c1d, {0x9a, 0x7e, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66}};
const GUID iid_nothing = {0x5e3a0c12, 0x0b0b, 0x4c1d, {0x9a, 0x7e, 0x11, 0x22, 0x33, 0x44, 0x55, 0x67}};

using QueryFn = HRESULT(WINAPI*)(const GUID&, const GUID&, void**);
using InitFn = HRESULT(WINAPI*)(ULONG, ULONG, char, const void*);
using UninitFn = HRESULT(WINAPI*)();

struct Options {
    UINT32 version;
    BOOLEAN inline_config;
    const char* config;
};

// A COM-shaped call through slot `slot` of `object`'s vtable (Win64 has one calling convention).
void** vtbl(void* object) { return *static_cast<void***>(object); }
template <typename R, typename... A>
R call(void* object, unsigned slot, A... args)
{
    return reinterpret_cast<R(__fastcall*)(void*, A...)>(vtbl(object)[slot])(object, args...);
}

QueryFn g_query;

void* query(const GUID& clsid, const GUID& iid, HRESULT want = S_OK)
{
    void* object = reinterpret_cast<void*>(0x1);
    const HRESULT hr = g_query(clsid, iid, &object);
    if (hr != want) {
        std::printf("FAIL query -> 0x%08lx, want 0x%08lx\n", static_cast<unsigned long>(hr), static_cast<unsigned long>(want));
        ++failures;
    }
    if (FAILED(hr)) CHECK(object == nullptr);
    return object;
}

HANDLE g_notified;
uint32_t g_hint_level;
void CALLBACK on_hint(void*, const void* hint)
{
    g_hint_level = *static_cast<const uint32_t*>(hint);
    SetEvent(g_notified);
}
void CALLBACK on_port(void*, uint16_t) {}

void unknown_class_and_slots()
{
    void* object = query(clsid_nothing, iid_nothing);
    if (!object) return;
    // Any slot answers E_NOTIMPL and is logged; none faults. Slot 15 with the argument shape a title was seen to use.
    CHECK_HR(call<HRESULT>(object, 15, static_cast<void*>(&g_notified), static_cast<uintptr_t>(0x7ffffffffffffffcull), static_cast<uintptr_t>(0x40)), notimpl);
    CHECK_HR(call<HRESULT>(object, 3), notimpl);
    CHECK_HR(call<HRESULT>(object, 255), notimpl);
    // IUnknown works, and an unrelated IID is accepted (a fallback object refuses nothing).
    void* other = nullptr;
    CHECK_HR(call<HRESULT>(object, 0, &iid_nothing, &other), S_OK);
    CHECK(other != nullptr);
    CHECK(call<ULONG>(object, 1) >= 1);
    CHECK(call<ULONG>(object, 2) >= 1);
    // The same IID with another class, and a known class with an unlisted IID, also give fallback objects.
    void* mismatch = query(clsid_user, iid_networking);  // another class's IID
    if (mismatch) CHECK_HR(call<HRESULT>(mismatch, 9), no_default_user);
    void* user_other_iid = query(clsid_user, iid_nothing);
    // XUser's fallback is "no default user", the answer a sign-in path expects.
    if (user_other_iid) CHECK_HR(call<HRESULT>(user_other_iid, 9), no_default_user);
}

void networking()
{
    void* net = query(clsid_networking, iid_networking);
    if (!net) return;
    // Slot 15 with the arguments a title used (a caller struct whose first qword is 0x20): unmapped, so it answers
    // E_NOTIMPL and must leave the struct exactly as it was (an earlier guess wrote into it: heap corruption).
    uint64_t title_struct[8] = {0x20, 0x297bbedf052ull, 0x1111, 0x2222, 0x3333, 0x4444, 0x5555, 0x6666};
    uint64_t before[8];
    std::memcpy(before, title_struct, sizeof before);
    CHECK_HR(call<HRESULT>(net, 15, static_cast<void*>(title_struct), static_cast<uintptr_t>(0x7ffffffffffffffcull), static_cast<uintptr_t>(0x40)), notimpl);
    CHECK(std::memcmp(before, title_struct, sizeof before) == 0);
    CHECK_HR(call<HRESULT>(net, 15, static_cast<void*>(nullptr)), notimpl);

    // Inferred slots (positions guessed from header order, not traced) are not served by default and never touch
    // their arguments: the connectivity hint (3), the registrations (4, 6) and the port query (17).
    unsigned char canary[64];
    std::memset(canary, 0xa5, sizeof canary);
    auto untouched = [&] {
        for (unsigned char b : canary)
            if (b != 0xa5) return false;
        return true;
    };
    if (!g_inferred) {
        CHECK_HR(call<HRESULT>(net, 3, static_cast<void*>(canary)), notimpl);
        CHECK(untouched());
        CHECK_HR(call<HRESULT>(net, 4, static_cast<XTaskQueueHandle>(nullptr), static_cast<void*>(nullptr),
                               reinterpret_cast<void*>(&on_hint), static_cast<void*>(canary)), notimpl);
        CHECK(untouched());
        CHECK_HR(call<HRESULT>(net, 17, static_cast<void*>(canary), static_cast<void*>(canary + 32)), notimpl);
        CHECK(untouched());
    } else {
        // X2W_XGR_INFERRED=1: the guesses are served (the experiment path).
        struct Hint {
            uint32_t level, cost, iana;
            bool initialized, approaching, over, roaming;
        } hint = {};
        CHECK_HR(call<HRESULT>(net, 3, &hint), S_OK);
        CHECK(hint.level == 3 && hint.cost == 1 && hint.initialized && !hint.approaching && !hint.over && !hint.roaming);

        // Register: a token, the initial notification on the process queue, then Unregister.
        g_notified = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        XTaskQueueRegistrationToken token = {};
        CHECK_HR(call<HRESULT>(net, 4, static_cast<XTaskQueueHandle>(nullptr), static_cast<void*>(nullptr),
                               reinterpret_cast<void*>(&on_hint), &token), S_OK);
        CHECK(token.token != 0);
        CHECK(WaitForSingleObject(g_notified, 10000) == WAIT_OBJECT_0);
        CHECK(g_hint_level == 3);
        CHECK(static_cast<bool>(call<unsigned char>(net, 5, token, false)));
        CHECK(!static_cast<bool>(call<unsigned char>(net, 5, token, false)));  // already unregistered

        XTaskQueueRegistrationToken port_token = {};
        CHECK_HR(call<HRESULT>(net, 6, static_cast<XTaskQueueHandle>(nullptr), static_cast<void*>(nullptr),
                               reinterpret_cast<void*>(&on_port), &port_token), S_OK);
        CHECK(static_cast<bool>(call<unsigned char>(net, 7, port_token, false)));
        // Slot 15 stays unmapped even here.
        CHECK_HR(call<HRESULT>(net, 15, static_cast<void*>(title_struct)), notimpl);
        CHECK(std::memcmp(before, title_struct, sizeof before) == 0);
    }

    // The slots that have no implementation (the security/Verify slots we do not serve, 18+) log and fail.
    CHECK_HR(call<HRESULT>(net, 8, static_cast<void*>(nullptr), static_cast<void*>(nullptr)), notimpl);
    CHECK_HR(call<HRESULT>(net, 18), notimpl);
    CHECK_HR(call<HRESULT>(net, 99), notimpl);
}

void user()
{
    void* threading = query(clsid_threading, clsid_threading);
    void* users = query(clsid_user, clsid_user);
    void* tags = query(clsid_user, iid_gamertag);
    if (!threading || !users || !tags) return;

    // XUserAddAsync (slot 7) with each documented option; AddUserResult (8); the handle's accessors (9-14).
    for (XUserAddOptions options : {XUserAddOptions::AddDefaultUserAllowingUI, XUserAddOptions::AddDefaultUserSilently}) {
        XAsyncBlock block = {};
        CHECK_HR(call<HRESULT>(users, 7, options, &block), S_OK);
        CHECK_HR(call<HRESULT>(threading, 3, &block, true), S_OK);  // XAsyncGetStatus(wait)
        XUserHandle handle = nullptr;
        CHECK_HR(call<HRESULT>(users, 8, &block, &handle), S_OK);
        CHECK(handle != nullptr);
        if (!handle) continue;
        if (g_inferred) {
            uint64_t id = 0;
            CHECK_HR(call<HRESULT>(users, 9, handle, &id), S_OK);
            CHECK(id != 0);
            XUserLocalId local = {};
            CHECK_HR(call<HRESULT>(users, 11, handle, &local), S_OK);
            CHECK(local.value != 0);
            bool guest = true;
            CHECK_HR(call<HRESULT>(users, 13, handle, &guest), S_OK);
            CHECK(!guest);
            XUserState state = XUserState::SignedOut;
            CHECK_HR(call<HRESULT>(users, 14, handle, &state), S_OK);
            CHECK(state == XUserState::SignedIn);
        } else {
            // The inferred accessors (9-14) are not served: "no default user", and the out-parameter untouched.
            uint64_t id = 0x5a5a5a5a5a5a5a5aull;
            CHECK_HR(call<HRESULT>(users, 9, handle, &id), no_default_user);
            CHECK(id == 0x5a5a5a5a5a5a5a5aull);
            XUserState state = static_cast<XUserState>(0x77);
            CHECK_HR(call<HRESULT>(users, 14, handle, &state), no_default_user);
            CHECK(static_cast<unsigned>(state) == 0x77);
        }
        char tag[32] = {};
        size_t used = 0;
        CHECK_HR(call<HRESULT>(tags, 3, handle, XUserGamertagComponent::Modern, sizeof tag, tag, &used), S_OK);
        CHECK(std::strcmp(tag, "Player") == 0);
        if (g_inferred) {
            XUserHandle copy = nullptr;
            CHECK_HR(call<HRESULT>(users, 3, handle, &copy), S_OK);  // XUserDuplicateHandle (inferred)
            CHECK(call<int>(users, 5, handle, copy) == 0);           // XUserCompare (inferred)
            call<void>(users, 4, copy);
        }
        call<void>(users, 4, handle);  // XUserCloseHandle (traced)
    }
    // A slot nothing is known about (RegisterForChangeEvent and the token functions have no traced position):
    // "no default user", logged.
    CHECK_HR(call<HRESULT>(users, 40, static_cast<void*>(nullptr), static_cast<void*>(nullptr)), no_default_user);
}

}  // namespace

int main(int argc, char** argv)
{
    const bool strict = argc > 2 && std::strcmp(argv[2], "strict") == 0;
    g_inferred = argc > 2 && std::strcmp(argv[2], "inferred") == 0;
    if (argc < 2) return 2;
    wchar_t path[MAX_PATH];
    MultiByteToWideChar(CP_UTF8, 0, argv[1], -1, path, MAX_PATH);
    HMODULE gateway = LoadLibraryExW(path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!gateway) {
        std::printf("FAIL cannot load the gateway (error %lu)\n", GetLastError());
        return 3;
    }
    g_query = reinterpret_cast<QueryFn>(GetProcAddress(gateway, "QueryApiImpl"));
    auto init = reinterpret_cast<InitFn>(GetProcAddress(gateway, "InitializeApiImplEx2"));
    auto uninit = reinterpret_cast<UninitFn>(GetProcAddress(gateway, "UninitializeApiImpl"));
    if (!g_query || !init || !uninit) {
        std::printf("FAIL missing exports\n");
        return 3;
    }
    const Options options = {1, FALSE, nullptr};
    CHECK_HR(init(10002, 7901, 0, &options), S_OK);

    if (strict) {
        // The old answer to an unlisted query, kept behind X2W_XGR_STRICT=1.
        void* object = query(clsid_nothing, iid_nothing, not_supported);
        CHECK(object == nullptr);
        object = query(clsid_user, iid_nothing, not_supported);
        CHECK(object == nullptr);
        void* net = query(clsid_networking, iid_networking);
        CHECK(net != nullptr);
    } else {
        unknown_class_and_slots();
        networking();
        user();
    }
    uninit();
    std::printf("xgr-gateway %s failures=%d\n", strict ? "strict" : g_inferred ? "inferred" : "fallback", failures);
    return failures ? 1 : 0;
}
