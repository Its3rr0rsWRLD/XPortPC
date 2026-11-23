// Gaming Runtime functions the gateway serves that x2w_gdk.dll has no implementation for (slots marked
// impl = "xgr" in tools/xgr/interfaces.toml). Signatures are the public flat functions of the GDK
// reference (learn.microsoft.com/gaming/gdk/docs/reference/system/...); each answers offline, like the
// x2w_gdk families (docs/design/runtime.md, section 2).
#include <windows.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <set>
#include <string>

#include "xgr_types.h"

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xthread/functions/xthreadassertnottimesensitive
// A debugging aid: the runtime breaks when the calling thread was marked time-sensitive. Nothing here is
// time-sensitive, so it succeeds.
HRESULT xgr_impl_XThreadAssertNotTimeSensitive(void) noexcept { return S_OK; }

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgameruntimefeature/functions/xgameruntimeisfeatureavailable
// No optional runtime feature is offered (libHttpClient then uses plain WinHTTP instead of XNetworking).
bool xgr_impl_XGameRuntimeIsFeatureAvailable(uint32_t /*feature*/) noexcept { return false; }

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xgame/functions/xgamegetxboxtitleid
// The title ID of the running game: the <TitleId> of the MicrosoftGame.config in the title's folder
// (X2W_TITLE_DIR, set by x2w_launch), else 0.
HRESULT xgr_impl_XGameGetXboxTitleId(uint32_t* titleId) noexcept
{
    if (!titleId) return E_INVALIDARG;
    static const uint32_t cached = [] {
        wchar_t dir[MAX_PATH] = {};
        if (!GetEnvironmentVariableW(L"X2W_TITLE_DIR", dir, MAX_PATH)) return 0u;
        const std::wstring path = std::wstring(dir) + L"\\MicrosoftGame.config";
        HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        if (file == INVALID_HANDLE_VALUE) return 0u;
        char text[16384] = {};
        DWORD read = 0;
        ReadFile(file, text, sizeof text - 1, &read, nullptr);
        CloseHandle(file);
        const char* tag = std::strstr(text, "<TitleId>");
        return tag ? static_cast<uint32_t>(std::strtoul(tag + 9, nullptr, 16)) : 0u;
    }();
    *titleId = cached;
    return S_OK;
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureasync
// The offline user's gamer picture: a 1x1 grey PNG, through the public XAsync provider protocol.
namespace {
const unsigned char gamer_picture[] = {
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00,
    0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xde, 0x00, 0x00, 0x00,
    0x0c, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63, 0x68, 0x68, 0x68, 0x00, 0x00, 0x03, 0x04, 0x01, 0x81, 0x75,
    0x2e, 0x01, 0xbc, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82};
const char gamer_picture_identity = 0;

HRESULT CALLBACK gamer_picture_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    switch (op) {
    case XAsyncOp::Begin:
        return x2w_impl_XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork:
        x2w_impl_XAsyncComplete(data->async, S_OK, sizeof gamer_picture);
        return S_OK;
    case XAsyncOp::GetResult:
        if (data->bufferSize < sizeof gamer_picture) return E_NOT_SUFFICIENT_BUFFER;
        std::memcpy(data->buffer, gamer_picture, sizeof gamer_picture);
        return S_OK;
    default:
        return S_OK;
    }
}
}  // namespace

HRESULT xgr_impl_XUserGetGamerPictureAsync(XUserHandle user, uint32_t /*pictureSize*/, XAsyncBlock* async) noexcept
{
    if (!user || !async) return E_INVALIDARG;
    return x2w_impl_XAsyncBegin(async, nullptr, &gamer_picture_identity, "XUserGetGamerPictureAsync",
                                gamer_picture_provider);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureresultsize
HRESULT xgr_impl_XUserGetGamerPictureResultSize(XAsyncBlock* async, size_t* bufferSize) noexcept
{
    return x2w_impl_XAsyncGetResultSize(async, bufferSize);
}

// https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/system/xuser/functions/xusergetgamerpictureresult
HRESULT xgr_impl_XUserGetGamerPictureResult(XAsyncBlock* async, size_t bufferSize, void* buffer,
                                             size_t* bufferUsed) noexcept
{
    return x2w_impl_XAsyncGetResult(async, &gamer_picture_identity, bufferSize, buffer, bufferUsed);
}

// ---------------------------------------------------------------- XNetworking
// The title's device is always online on an unmetered wired connection with the network initialized: the offline
// runtime has no network state to report, and "connected, unconstrained" is what lets a title past its
// "wait for the network" step. https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/networking/xnetworking/
// Every out-parameter is checked for writability first (a wrong slot guess must not fault the title); the
// slot-to-function mapping of tools/xgr/interfaces.toml is an inference, logged on its first use.
namespace {

constexpr uint16_t preferred_udp_port = 3074;  // "This port defaults to UDP 3074" (xnetworkingquerypreferredlocaludpmultiplayerport)
constexpr uint32_t iana_ethernet_csmacd = 6;

bool writable(const void* p, size_t n)
{
    MEMORY_BASIC_INFORMATION info;
    if (!p || !VirtualQuery(p, &info, sizeof info) || info.State != MEM_COMMIT) return false;
    if (info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) return false;
    constexpr DWORD any_write = PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    if (!(info.Protect & any_write)) return false;
    return reinterpret_cast<uintptr_t>(p) + n <= reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize;
}

void assumed(const char* function, unsigned slot)
{
    char detail[160];
    std::snprintf(detail, sizeof detail, "XNetworking slot %u taken to be %s (tools/xgr/interfaces.toml: inferred, not traced)",
                  slot, function);
    x2w_note("xgr-assume", detail);
}

XNetworkingConnectivityHint connected_hint()
{
    XNetworkingConnectivityHint hint = {};
    hint.connectivityLevel = XNetworkingConnectivityLevelHint::InternetAccess;
    hint.connectivityCost = XNetworkingConnectivityCostHint::Unrestricted;
    hint.ianaInterfaceType = iana_ethernet_csmacd;
    hint.networkInitialized = true;
    return hint;
}

// Registrations: the token's callbacks still alive (an unregister before the initial notification cancels it).
std::mutex g_net_lock;
std::set<uint64_t> g_net_tokens;
std::atomic<uint64_t> g_net_next{0x584e455400000001ull};  // "XNET" high half, so a token is easy to spot in a log

struct Notification {
    uint64_t token;
    void* context;
    XNetworkingConnectivityHintChangedCallback* hint_callback;
    XNetworkingPreferredLocalUdpMultiplayerPortChangedCallback* port_callback;
};

void CALLBACK deliver(void* raw, bool canceled)
{
    std::unique_ptr<Notification> note(static_cast<Notification*>(raw));
    if (canceled) return;
    {
        std::lock_guard<std::mutex> hold(g_net_lock);
        if (!g_net_tokens.count(note->token)) return;
    }
    if (note->hint_callback) {
        const XNetworkingConnectivityHint hint = connected_hint();
        note->hint_callback(note->context, &hint);
    } else if (note->port_callback) {
        note->port_callback(note->context, preferred_udp_port);
    }
}

// Both Register functions: the registration is kept and the documented initial notification is queued on the
// completion port of the title's queue (null: the process queue).
HRESULT register_changed(XTaskQueueHandle queue, void* context, XNetworkingConnectivityHintChangedCallback* hint_callback,
                         XNetworkingPreferredLocalUdpMultiplayerPortChangedCallback* port_callback,
                         XTaskQueueRegistrationToken* token)
{
    if (token) token->token = 0;
    if (!token || !writable(token, sizeof *token)) return E_POINTER;
    if (!hint_callback && !port_callback) return E_INVALIDARG;
    const uint64_t value = g_net_next.fetch_add(1);
    {
        std::lock_guard<std::mutex> hold(g_net_lock);
        g_net_tokens.insert(value);
    }
    token->token = value;
    auto* note = new Notification{value, context, hint_callback, port_callback};
    if (FAILED(x2w_impl_XTaskQueueSubmitCallback(queue, XTaskQueuePort::Completion, note, &deliver))) {
        delete note;  // no usable queue: the registration stands, only the initial notification is lost
        x2w_note("xgr-networking", "initial notification not queued (no usable task queue)");
    }
    return S_OK;
}

bool unregister(XTaskQueueRegistrationToken token)
{
    std::lock_guard<std::mutex> hold(g_net_lock);
    return g_net_tokens.erase(token.token) != 0;
}

const char port_identity = 0;

HRESULT CALLBACK port_provider(XAsyncOp op, const XAsyncProviderData* data)
{
    switch (op) {
    case XAsyncOp::Begin: return x2w_impl_XAsyncSchedule(data->async, 0);
    case XAsyncOp::DoWork: x2w_impl_XAsyncComplete(data->async, S_OK, sizeof(uint16_t)); return S_OK;
    case XAsyncOp::GetResult:
        if (data->bufferSize < sizeof(uint16_t)) return E_NOT_SUFFICIENT_BUFFER;
        *static_cast<uint16_t*>(data->buffer) = preferred_udp_port;
        return S_OK;
    default: return S_OK;
    }
}

}  // namespace

// .../xnetworking/functions/xnetworkinggetconnectivityhint
HRESULT xgr_impl_XNetworkingGetConnectivityHint(XNetworkingConnectivityHint* connectivityHint) noexcept
{
    assumed("XNetworkingGetConnectivityHint", 3);
    if (!writable(connectivityHint, sizeof *connectivityHint)) return E_POINTER;
    *connectivityHint = connected_hint();
    return S_OK;
}

// .../xnetworking/functions/xnetworkingregisterconnectivityhintchanged
HRESULT xgr_impl_XNetworkingRegisterConnectivityHintChanged(XTaskQueueHandle queue, void* context,
                                                            XNetworkingConnectivityHintChangedCallback* callback,
                                                            XTaskQueueRegistrationToken* token) noexcept
{
    assumed("XNetworkingRegisterConnectivityHintChanged", 4);
    return register_changed(queue, context, callback, nullptr, token);
}

// .../xnetworking/functions/xnetworkingunregisterconnectivityhintchanged
bool xgr_impl_XNetworkingUnregisterConnectivityHintChanged(XTaskQueueRegistrationToken token, bool /*wait*/) noexcept
{
    assumed("XNetworkingUnregisterConnectivityHintChanged", 5);
    return unregister(token);
}

// .../xnetworking/functions/xnetworkingregisterpreferredlocaludpmultiplayerportchanged
HRESULT xgr_impl_XNetworkingRegisterPreferredLocalUdpMultiplayerPortChanged(
    XTaskQueueHandle queue, void* context, XNetworkingPreferredLocalUdpMultiplayerPortChangedCallback* callback,
    XTaskQueueRegistrationToken* token) noexcept
{
    assumed("XNetworkingRegisterPreferredLocalUdpMultiplayerPortChanged", 6);
    return register_changed(queue, context, nullptr, callback, token);
}

// .../xnetworking/functions/xnetworkingunregisterpreferredlocaludpmultiplayerportchanged
bool xgr_impl_XNetworkingUnregisterPreferredLocalUdpMultiplayerPortChanged(XTaskQueueRegistrationToken token,
                                                                           bool /*wait*/) noexcept
{
    assumed("XNetworkingUnregisterPreferredLocalUdpMultiplayerPortChanged", 7);
    return unregister(token);
}

// .../xnetworking/functions/xnetworkingquerypreferredlocaludpmultiplayerportasync
HRESULT xgr_impl_XNetworkingQueryPreferredLocalUdpMultiplayerPortAsync(XAsyncBlock* asyncBlock) noexcept
{
    assumed("XNetworkingQueryPreferredLocalUdpMultiplayerPortAsync", 16);
    if (!asyncBlock) return E_INVALIDARG;
    return x2w_impl_XAsyncBegin(asyncBlock, nullptr, &port_identity, "XNetworkingQueryPreferredLocalUdpMultiplayerPortAsync",
                                port_provider);
}

// .../xnetworking/functions/xnetworkingquerypreferredlocaludpmultiplayerportasyncresult
HRESULT xgr_impl_XNetworkingQueryPreferredLocalUdpMultiplayerPortAsyncResult(
    XAsyncBlock* asyncBlock, uint16_t* preferredLocalUdpMultiplayerPort) noexcept
{
    assumed("XNetworkingQueryPreferredLocalUdpMultiplayerPortAsyncResult", 17);
    if (!writable(preferredLocalUdpMultiplayerPort, sizeof(uint16_t))) return E_POINTER;
    return x2w_impl_XAsyncGetResult(asyncBlock, &port_identity, sizeof(uint16_t), preferredLocalUdpMultiplayerPort, nullptr);
}
